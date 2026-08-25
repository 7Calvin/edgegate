"""
User Management Routes
"""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db.session import get_db
from app.models.user import User, UserType, AuthSource
from app.services.user_service import UserService
from app.dependencies.auth import get_current_active_user, require_admin
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    ServiceAccountCreate,
    ServiceAccountResponse,
    UserMeResponse,
    TrustedHostsUpdate,
    TrustedHostsResponse,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.auth import APIKeyResponse

router = APIRouter()


# ==================== Current User Routes ====================

@router.get("/me", response_model=UserMeResponse)
async def get_current_user_profile(
    user: User = Depends(get_current_active_user)
):
    """Get current user's profile"""
    return user


@router.patch("/me", response_model=UserMeResponse)
async def update_current_user_profile(
    data: UserUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update current user's profile.

    Note: Users cannot change their own admin status or mfa_required.
    """
    # Remove fields that users can't change for themselves
    update_data = data.model_dump(exclude_unset=True)
    restricted_fields = ["is_admin", "mfa_required", "is_active", "expires_at"]
    for field in restricted_fields:
        update_data.pop(field, None)

    if not update_data:
        return user

    user_service = UserService(db)

    # Create a new UserUpdate with only allowed fields
    allowed_update = UserUpdate(**update_data)
    updated_user, error = await user_service.update_user(user, allowed_update, user)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    return updated_user


# ==================== Admin User Management Routes ====================

@router.get("", response_model=PaginatedResponse[UserListResponse])
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user_type: Optional[UserType] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    auth_source: Optional[AuthSource] = None,
    is_admin: Optional[bool] = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all users (admin only).

    Supports filtering by type, auth source (ad/local), admin flag, status, and search.
    """
    user_service = UserService(db)

    users, total = await user_service.list_users(
        skip=(page - 1) * per_page,
        limit=per_page,
        user_type=user_type,
        is_active=is_active,
        search=search,
        auth_source=auth_source,
        is_admin=is_admin,
    )

    return PaginatedResponse.create(
        items=[UserListResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        per_page=per_page
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create a new user (admin only) - also creates VPN profile automatically"""
    user_service = UserService(db)

    user, error = await user_service.create_user(data, created_by=admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    # Automatically create VPN profile for the new user
    from app.services.vpn_service import VPNService
    from app.schemas.vpn import VPNProfileCreate

    vpn_service = VPNService(db)
    vpn_data = VPNProfileCreate(user_id=user.id)
    profile, vpn_error = await vpn_service.create_profile(user, vpn_data)

    if vpn_error:
        # Log but don't fail - user was created successfully
        import logging
        logging.getLogger(__name__).warning(f"Failed to create VPN profile for user {user.username}: {vpn_error}")

    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID (admin only)"""
    user_service = UserService(db)

    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user


@router.post("/{user_id}/mfa/reset", response_model=MessageResponse)
async def reset_user_mfa(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset (remove) MFA on a user's account (admin only).

    Clears the enrolled TOTP secret and backup codes so the user can enroll fresh — the
    admin recovery path for someone who lost their authenticator. If the account is
    mfa_required, the user is prompted to set MFA up again on their next login."""
    user_service = UserService(db)
    target = await user_service.get_by_id(user_id)

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not target.mfa_enabled and not target.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no MFA to reset"
        )

    target.mfa_enabled = False
    target.mfa_secret = None
    target.mfa_backup_codes = []
    await db.commit()

    return MessageResponse(message=f"MFA reset for {target.username}")


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update user (admin only)"""
    user_service = UserService(db)

    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent admin from disabling themselves
    update_data = data.model_dump(exclude_unset=True)
    if user.id == admin.id and update_data.get('is_active') is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account"
        )

    # Prevent admin from removing their own admin role
    if user.id == admin.id and update_data.get('is_admin') is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin role"
        )

    # Prevent removing admin from the last active admin (lockout protection)
    if 'is_admin' in update_data and update_data['is_admin'] is False and user.is_admin:
        admin_count = await user_service.count_active_admins()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin. Promote another user first."
            )

    updated_user, error = await user_service.update_user(user, data, admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    return updated_user


@router.put("/{user_id}/trusted-hosts", response_model=TrustedHostsResponse)
async def update_trusted_hosts(
    user_id: UUID,
    data: TrustedHostsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Replace a user's Trusted Hosts (source-IP allowlist). Admin only.

    Applies to admins and service accounts; plain VPN users are not subject to
    Trusted Hosts. An empty list clears the restriction. Setting a list that does
    not cover your own current IP will lock you out on the next request — the
    frontend warns first, and recovery is via the local ``vpnctl`` CLI.
    """
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.is_subject_to_trusted_hosts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Trusted Hosts apply only to admins and service accounts.",
        )

    user.allowed_source_ips = data.allowed_source_ips
    await db.commit()
    await db.refresh(user)

    return TrustedHostsResponse(
        id=user.id,
        username=user.username,
        allowed_source_ips=[str(ip) for ip in (user.allowed_source_ips or [])],
    )


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: UUID,
    permanent: bool = Query(False, description="Permanently delete user"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete user (admin only).

    By default, performs soft delete (deactivation).
    Use permanent=true for hard delete.
    """
    user_service = UserService(db)

    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    if permanent:
        success = await user_service.hard_delete_user(user, admin)
        message = "User permanently deleted"
    else:
        success = await user_service.delete_user(user, admin)
        message = "User deactivated"

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to delete user"
        )

    return MessageResponse(message=message)


class ResetPasswordResponse(BaseModel):
    message: str
    new_password: str


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_user_password(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Reset user's password (admin only) - generates a random password"""
    import secrets
    import string

    user_service = UserService(db)

    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Generate a random password that meets requirements
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        new_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        # Ensure it has all required character types
        if (any(c.islower() for c in new_password)
                and any(c.isupper() for c in new_password)
                and any(c.isdigit() for c in new_password)
                and any(c in "!@#$%^&*" for c in new_password)):
            break

    await user_service.reset_password(user, new_password)

    return ResetPasswordResponse(
        message="Password reset successfully",
        new_password=new_password
    )


# ==================== Service Account Routes ====================

@router.post("/service-accounts", response_model=ServiceAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_service_account(
    data: ServiceAccountCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new service account (admin only).

    Returns the API key ONCE. Store it securely.
    """
    user_service = UserService(db)

    user, error, api_key = await user_service.create_service_account(data, created_by=admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    response = ServiceAccountResponse.model_validate(user)
    response.api_key_prefix = api_key[:8] if api_key else None
    response.api_key = api_key  # Full key returned only on creation

    return response


@router.post("/service-accounts/{user_id}/regenerate-key", response_model=APIKeyResponse)
async def regenerate_service_account_key(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Regenerate API key for service account (admin only).

    The old key will be invalidated immediately.
    """
    user_service = UserService(db)

    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service account not found"
        )

    if user.user_type != UserType.SERVICE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a service account"
        )

    api_key, error = await user_service.regenerate_api_key(user)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    from datetime import datetime
    return APIKeyResponse(
        api_key=api_key,
        key_prefix=api_key[:8],
        created_at=datetime.utcnow()
    )


# ==================== Stats Routes ====================

@router.get("/stats/summary")
async def get_user_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get user statistics (admin only)"""
    user_service = UserService(db)
    return await user_service.get_user_stats()
