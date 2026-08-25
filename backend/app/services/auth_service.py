"""
Authentication Service - Handles login, MFA, tokens
"""
from typing import Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import logging

from app.models.user import User, UserType, AuthSource
from app.core.config import settings
from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_mfa_secret,
    generate_mfa_qr_code,
    verify_mfa_token,
    generate_backup_codes,
    hash_backup_code,
    verify_backup_code,
    generate_api_key,
    hash_api_key,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication service"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def authenticate_user(
        self,
        username: str,
        password: str,
        mfa_code: Optional[str] = None,
        client_ip: Optional[str] = None
    ) -> Tuple[Optional[User], Optional[str], bool]:
        """
        Authenticate user with username/password and optional MFA.

        Returns:
            Tuple of (user, error_message, mfa_pending)
            - If successful: (user, None, False)
            - If MFA needed: (user, None, True)
            - If failed: (None, error_message, False)
        """
        # Find user
        result = await self.db.execute(
            select(User).where(User.username == username.lower())
        )
        user = result.scalar_one_or_none()

        # Trusted Hosts (source-IP allowlist): gate BEFORE verifying the password,
        # so a request from a non-allowed IP is refused identically whether or not
        # the credentials are valid — no password-validity oracle for an attacker
        # coming from a blocked network. Applies to admins and service accounts;
        # plain VPN users are exempt (see User.is_source_ip_trusted).
        if user is not None and not user.is_source_ip_trusted(client_ip):
            logger.warning(f"Login for {username} denied from untrusted IP: {client_ip}")
            return None, "Access denied from this IP address", False

        # Decide the credential store per user:
        #   - Known LOCAL account -> verify against the local database (always works,
        #     independent of AD being enabled or reachable).
        #   - Unknown user, or an AD-backed account -> verify against Active Directory.
        local_password_account = (
            user is not None
            and user.auth_source == AuthSource.LOCAL
            and user.password_hash
        )

        if local_password_account:
            # Verify password (or API key for service accounts)
            password_valid = verify_password(password, user.password_hash)
            if not password_valid and user.user_type == UserType.SERVICE and user.api_key_hash:
                password_valid = hash_api_key(password) == user.api_key_hash
            if not password_valid:
                logger.warning(f"Invalid password for user: {username}")
                return None, "Invalid username or password", False
        else:
            # Active Directory path (unknown user or auth_source == 'ad').
            user, ad_error = await self._authenticate_ad(username, password, user)
            if ad_error:
                return None, ad_error, False

        # Check if active
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {username}")
            return None, "Account is disabled", False

        # Check if expired
        if user.is_expired:
            logger.warning(f"Login attempt for expired user: {username}")
            return None, "Account has expired", False

        # Check MFA
        if user.requires_mfa_on_login:
            if not mfa_code:
                # MFA required but not provided
                return user, None, True

            # Verify MFA code
            if not self._verify_mfa_or_backup(user, mfa_code):
                logger.warning(f"Invalid MFA code for user: {username}")
                return None, "Invalid MFA code", False

        # Update last login
        await self._update_last_login(user, client_ip)

        return user, None, False

    async def _authenticate_ad(
        self,
        username: str,
        password: str,
        existing_user: Optional[User],
    ) -> Tuple[Optional[User], Optional[str]]:
        """
        Authenticate against Active Directory and JIT-provision a local shadow user.

        The shadow user gives connections/quotas/firewall something local to attach
        to; AD remains the source of truth for password and group membership.

        Returns (user, error): (user, None) on success, (None, message) on failure.
        """
        from app.services.ldap_service import LdapService

        ldap = LdapService(self.db)
        ok, attrs, error = await ldap.authenticate(username, password)
        if not ok:
            logger.warning(f"AD auth failed for '{username}': {error}")
            # Keep the message generic for unknown users; specific hints only help
            # a configured-but-denied case (e.g. not in group).
            if existing_user is None and error in (None, "LDAP is not enabled"):
                return None, "Invalid username or password"
            return None, error or "Invalid username or password"

        # Success: reuse the existing shadow record or create one now.
        user = existing_user
        if user is None:
            user = await self._provision_ad_user(username, attrs)
        elif attrs and attrs.get("email") and not user.email:
            user.email = attrs["email"]
            await self.db.commit()

        return user, None

    async def _provision_ad_user(self, username: str, attrs: Optional[dict]) -> User:
        """Create a local shadow user for an AD-authenticated identity (JIT)."""
        from sqlalchemy.exc import IntegrityError

        user = User(
            username=username.lower(),
            email=(attrs or {}).get("email"),
            password_hash=None,
            user_type=UserType.HUMAN,
            auth_source=AuthSource.AD,
            is_active=True,
        )
        self.db.add(user)
        try:
            await self.db.commit()
            await self.db.refresh(user)
            logger.info(f"JIT-provisioned AD shadow user: {username}")
            return user
        except IntegrityError:
            # Concurrent first login created it first — re-fetch the existing row.
            await self.db.rollback()
            result = await self.db.execute(
                select(User).where(User.username == username.lower())
            )
            return result.scalar_one()

    def _verify_mfa_or_backup(self, user: User, code: str) -> bool:
        """Verify MFA code or backup code"""
        # Try regular MFA code first
        if verify_mfa_token(user.mfa_secret, code):
            return True

        # Try backup codes
        if user.mfa_backup_codes:
            for i, hashed_code in enumerate(user.mfa_backup_codes):
                if verify_backup_code(code.replace("-", "").upper(), hashed_code):
                    # Remove used backup code
                    new_codes = user.mfa_backup_codes.copy()
                    new_codes.pop(i)
                    user.mfa_backup_codes = new_codes
                    logger.info(f"Backup code used for user: {user.username}")
                    return True

        return False

    async def _update_last_login(self, user: User, client_ip: Optional[str]):
        """Update user's last login timestamp and IP"""
        await self.db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                last_login_at=datetime.utcnow(),
                last_login_ip=client_ip
            )
        )
        await self.db.commit()

    def create_tokens(
        self,
        user: User,
        mfa_pending: bool = False
    ) -> dict:
        """
        Create access and refresh tokens for user.

        Args:
            user: The authenticated user
            mfa_pending: If True, creates a limited token that requires MFA verification

        Returns:
            dict with access_token, refresh_token, expires_in
        """
        token_data = {
            "sub": str(user.id),
            "username": user.username,
            "is_admin": user.is_admin,
            "user_type": user.user_type.value,
        }

        if mfa_pending:
            token_data["mfa_pending"] = True
            # Short expiration for MFA pending tokens
            expires_delta = timedelta(minutes=5)
        else:
            expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        access_token = create_access_token(token_data, expires_delta)
        refresh_token = create_refresh_token({"sub": str(user.id)})

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": int(expires_delta.total_seconds()),
        }

    async def refresh_access_token(self, refresh_token: str) -> Optional[dict]:
        """
        Refresh access token using refresh token.

        Returns:
            New tokens dict or None if invalid
        """
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        # Get user
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_active or user.is_expired:
            return None

        return self.create_tokens(user)

    async def setup_mfa(self, user: User) -> dict:
        """
        Setup MFA for user.

        Returns:
            dict with secret, qr_code, backup_codes
        """
        # Generate new secret
        secret = generate_mfa_secret()

        # Generate QR code
        qr_code = generate_mfa_qr_code(user.username, secret)

        # Generate backup codes
        raw_backup_codes = generate_backup_codes(10)
        hashed_backup_codes = [hash_backup_code(code.replace("-", "")) for code in raw_backup_codes]

        # Update user (MFA not enabled yet - requires verification)
        user.mfa_secret = secret
        user.mfa_backup_codes = hashed_backup_codes
        await self.db.commit()

        return {
            "secret": secret,
            "qr_code": qr_code,
            "backup_codes": raw_backup_codes,
        }

    async def verify_and_enable_mfa(self, user: User, code: str) -> bool:
        """
        Verify MFA code and enable MFA for user.

        Returns:
            True if successful, False if invalid code
        """
        if not user.mfa_secret:
            return False

        if not verify_mfa_token(user.mfa_secret, code):
            return False

        # Enable MFA
        user.mfa_enabled = True
        await self.db.commit()

        logger.info(f"MFA enabled for user: {user.username}")
        return True

    async def disable_mfa(self, user: User, password: str, mfa_code: Optional[str] = None) -> Tuple[bool, str]:
        """
        Disable MFA for user.

        The password is always required. A TOTP code is optional: when supplied it must be
        valid, but when omitted the password alone authorises removal — the recovery path
        for a user who lost their authenticator.

        Returns:
            (success, message)
        """
        # Verify password (always required)
        if not verify_password(password, user.password_hash):
            return False, "Invalid password"

        # If a TOTP code was supplied, it must match. Omitting it is allowed (password-only).
        if mfa_code and not verify_mfa_token(user.mfa_secret, mfa_code):
            return False, "Invalid MFA code"

        # Disable MFA
        user.mfa_enabled = False
        user.mfa_secret = None
        user.mfa_backup_codes = []
        await self.db.commit()

        logger.info(f"MFA disabled for user: {user.username}")
        return True, "MFA disabled successfully"

    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str
    ) -> Tuple[bool, str]:
        """
        Change user's password.

        Returns:
            (success, message)
        """
        # Verify current password
        if not verify_password(current_password, user.password_hash):
            return False, "Current password is incorrect"

        # Hash and save new password
        user.password_hash = hash_password(new_password)
        await self.db.commit()

        logger.info(f"Password changed for user: {user.username}")
        return True, "Password changed successfully"

    async def generate_api_key_for_user(self, user: User) -> Tuple[str, str]:
        """
        Generate new API key for service account.

        Returns:
            (api_key, key_prefix)
        """
        if user.user_type != UserType.SERVICE:
            raise ValueError("API keys can only be generated for service accounts")

        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        key_prefix = api_key[:8]

        user.api_key_hash = key_hash
        await self.db.commit()

        logger.info(f"New API key generated for service account: {user.username}")
        return api_key, key_prefix

    async def verify_mfa_for_pending_login(
        self,
        user_id: str,
        mfa_code: str
    ) -> Optional[User]:
        """
        Verify MFA code for a pending login.

        Returns:
            User if successful, None if invalid
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return None

        if not self._verify_mfa_or_backup(user, mfa_code):
            return None

        return user
