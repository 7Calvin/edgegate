"""
Authentication Routes
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User, UserType
from app.services.auth_service import AuthService
from app.dependencies.auth import get_current_user, get_current_active_user
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    TokenResponse,
    RefreshTokenRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    MFADisableRequest,
    PasswordChangeRequest,
    SessionInfo,
)
from app.schemas.common import MessageResponse
from app.core.net import get_trusted_client_ip
from app.core.rate_limit import (
    check_login_allowed,
    record_login_failure,
    record_login_success,
)

router = APIRouter()


def get_client_ip(request: Request) -> Optional[str]:
    """Resolve the client IP via the trusted-proxy chain (anti-spoof)."""
    return get_trusted_client_ip(request)


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and return tokens.

    - If MFA is enabled and code not provided, returns mfa_pending=True
    - Client should then call /auth/mfa/verify with the code
    """
    auth_service = AuthService(db)
    client_ip = get_client_ip(request)

    # Brute-force protection: reject once the per-IP / per-username failure
    # window is exhausted (H2). Fails open if Redis is unavailable.
    rl = await check_login_allowed(client_ip, data.username)
    if rl.limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(rl.retry_after)},
        )

    user, error, mfa_pending = await auth_service.authenticate_user(
        username=data.username,
        password=data.password,
        mfa_code=data.mfa_code,
        client_ip=client_ip
    )

    if error:
        await record_login_failure(client_ip, data.username)
        from app.services.audit_service import record_event
        await record_event(
            action="Falha de login", resource_type="auth", username=data.username,
            ip=client_ip, user_agent=request.headers.get("user-agent"),
            details={"reason": error}, severity="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error
        )

    # Correct credentials -> clear the failure counters for this IP/username.
    await record_login_success(client_ip, data.username)

    # Block service accounts from web console login
    if user.user_type == UserType.SERVICE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service accounts cannot login via web console. Use API key authentication."
        )

    tokens = auth_service.create_tokens(user, mfa_pending=mfa_pending)

    if not mfa_pending:
        from app.services.audit_service import record_event
        await record_event(
            action="Login no painel", resource_type="auth", user_id=user.id,
            username=user.username, ip=client_ip, user_agent=request.headers.get("user-agent"),
            severity="info",
        )

    return LoginResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        user_id=str(user.id),
        username=user.username,
        is_admin=user.is_admin,
        mfa_enabled=user.mfa_enabled,
        mfa_required=user.mfa_required,
        mfa_pending=mfa_pending
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token"""
    auth_service = AuthService(db)

    tokens = await auth_service.refresh_access_token(data.refresh_token)

    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"]
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    user: User = Depends(get_current_user)
):
    """
    Logout current user.

    Note: JWT tokens are stateless, so this endpoint is mainly for
    client-side token cleanup. For true invalidation, implement
    token blacklisting with Redis.
    """
    # TODO: Add token to blacklist in Redis
    return MessageResponse(message="Logged out successfully")


class WhoAmIResponse(BaseModel):
    """Server-observed identity of the current request."""
    client_ip: Optional[str] = None


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(
    request: Request,
    user: User = Depends(get_current_active_user),
):
    """Return the client IP as resolved through the trusted proxy chain.

    Powers the anti-lockout hint in the Trusted Hosts editor: the admin can see
    exactly which IP the server attributes to them before saving an allowlist.
    """
    return WhoAmIResponse(client_ip=get_client_ip(request))


@router.get("/me", response_model=SessionInfo)
async def get_current_session(
    user: User = Depends(get_current_active_user)
):
    """Get current session/user information"""
    from datetime import datetime, timedelta
    from app.core.config import settings

    return SessionInfo(
        user_id=str(user.id),
        username=user.username,
        user_type=user.user_type.value,
        is_admin=user.is_admin,
        mfa_enabled=user.mfa_enabled,
        mfa_required=user.mfa_required,
        issued_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


# ==================== MFA Routes ====================

@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Setup MFA for current user.

    Returns QR code and backup codes. User must verify with /mfa/verify
    to actually enable MFA.
    """
    if user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled"
        )

    auth_service = AuthService(db)
    result = await auth_service.setup_mfa(user)

    return MFASetupResponse(
        secret=result["secret"],
        qr_code=result["qr_code"],
        backup_codes=result["backup_codes"]
    )


@router.post("/mfa/verify", response_model=MessageResponse)
async def verify_mfa_setup(
    data: MFAVerifyRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify MFA code to complete setup.

    This enables MFA after user has scanned QR code.
    """
    if user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled"
        )

    if not user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup not initiated. Call /mfa/setup first"
        )

    auth_service = AuthService(db)
    success = await auth_service.verify_and_enable_mfa(user, data.code)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA code"
        )

    return MessageResponse(message="MFA enabled successfully")


@router.post("/mfa/disable", response_model=MessageResponse)
async def disable_mfa(
    data: MFADisableRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disable MFA for current user.

    Requires the account password. The current TOTP code is optional — omitting it lets a
    user who lost their authenticator still remove MFA with their password alone. Blocked
    when the admin marked the account mfa_required.
    """
    if not user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled"
        )

    # Check if MFA is required by admin
    if user.mfa_required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA is required for your account and cannot be disabled"
        )

    auth_service = AuthService(db)
    success, message = await auth_service.disable_mfa(user, data.password, data.mfa_code)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return MessageResponse(message=message)


@router.post("/mfa/verify-login", response_model=LoginResponse)
async def verify_mfa_login(
    data: MFAVerifyRequest,
    user: User = Depends(get_current_user),  # Allows MFA pending tokens
    db: AsyncSession = Depends(get_db)
):
    """
    Complete login by verifying MFA code.

    Called after initial login returns mfa_pending=True.
    """
    auth_service = AuthService(db)

    verified_user = await auth_service.verify_mfa_for_pending_login(
        str(user.id),
        data.code
    )

    if not verified_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA code"
        )

    # Create new tokens without MFA pending
    tokens = auth_service.create_tokens(verified_user, mfa_pending=False)

    return LoginResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        user_id=str(verified_user.id),
        username=verified_user.username,
        is_admin=verified_user.is_admin,
        mfa_enabled=verified_user.mfa_enabled,
        mfa_required=verified_user.mfa_required,
        mfa_pending=False
    )


# ==================== Password Routes ====================

@router.post("/password/change", response_model=MessageResponse)
async def change_password(
    data: PasswordChangeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Change current user's password"""
    auth_service = AuthService(db)

    success, message = await auth_service.change_password(
        user,
        data.current_password,
        data.new_password
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return MessageResponse(message=message)
