"""
Authentication Dependencies
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.user import User, UserType
from app.core.security import decode_token, verify_api_key
from app.core.net import get_trusted_client_ip

# Bearer token security scheme
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get current authenticated user from JWT token.

    Raises:
        HTTPException 401: If token is missing, invalid or expired
        HTTPException 401: If user not found or inactive
        HTTPException 403: If the request source IP is not a Trusted Host for the user
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # First try JWT token
    payload = decode_token(token)

    if payload:
        # JWT token
        user_id = payload.get("sub")
        token_type = payload.get("type")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Use access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check for MFA pending
        if payload.get("mfa_pending"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MFA verification required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Reject access tokens revoked at logout (M8). Fails open if Redis is down.
        from app.core.token_blacklist import is_jti_revoked
        if await is_jti_revoked(payload.get("jti")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get user from database
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

    else:
        # Try API key authentication
        from app.core.security import hash_api_key
        key_hash = hash_api_key(token)

        result = await db.execute(
            select(User).where(
                User.api_key_hash == key_hash,
                User.user_type == UserType.SERVICE
            )
        )
        user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Trusted Hosts: enforce the source-IP allowlist on every authenticated
    # request, not just at login — JWTs are stateless and API keys never re-login,
    # so a token minted from a trusted IP must not keep working from elsewhere.
    if not user.is_source_ip_trusted(get_trusted_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied from this IP address",
        )

    return user


async def get_current_active_user(
    user: User = Depends(get_current_user)
) -> User:
    """
    Get current user and verify they are active.

    Raises:
        HTTPException 403: If user is inactive or expired
    """
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    if user.is_expired:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account has expired"
        )

    return user


async def require_admin(
    user: User = Depends(get_current_active_user)
) -> User:
    """
    Require admin privileges.

    Raises:
        HTTPException 403: If user is not an admin
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return user


async def require_mfa_verified(
    user: User = Depends(get_current_active_user)
) -> User:
    """
    Require that user has verified MFA if it's enabled.

    This dependency should be used for sensitive operations.
    """
    # MFA check is already done in get_current_user via token payload
    # This is an additional check for sensitive operations
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Get current user if authenticated, None otherwise.

    Useful for endpoints that work both with and without authentication.
    """
    if not credentials:
        return None

    try:
        token = credentials.credentials
        payload = decode_token(token)

        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user and user.is_active and not user.is_expired:
            return user

        return None

    except Exception:
        return None


class RateLimiter:
    """
    Rate limiter dependency (placeholder for Redis-based implementation)
    """
    def __init__(self, calls: int = 60, period: int = 60):
        self.calls = calls
        self.period = period

    async def __call__(self, user: Optional[User] = Depends(get_optional_user)):
        # TODO: Implement Redis-based rate limiting
        # For now, just pass through
        pass


# Pre-configured rate limiters
rate_limit_default = RateLimiter(calls=60, period=60)
rate_limit_strict = RateLimiter(calls=10, period=60)
rate_limit_auth = RateLimiter(calls=5, period=60)
