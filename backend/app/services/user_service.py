"""
User Service - Handles user CRUD operations
"""
from typing import Optional, List, Tuple
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, or_
from sqlalchemy.orm import selectinload
import logging

from app.models.user import User, UserType, AuthSource
from app.core.security import hash_password, generate_api_key, hash_api_key
from app.schemas.user import UserCreate, UserUpdate, ServiceAccountCreate

logger = logging.getLogger(__name__)


class UserService:
    """User management service"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        result = await self.db.execute(
            select(User).where(User.username == username.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        skip: int = 0,
        limit: int = 20,
        user_type: Optional[UserType] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        auth_source: Optional[AuthSource] = None,
        is_admin: Optional[bool] = None,
    ) -> Tuple[List[User], int]:
        """
        List users with filtering and pagination.

        Returns:
            (list of users, total count)
        """
        query = select(User)

        # Apply filters
        if user_type:
            query = query.where(User.user_type == user_type)

        if auth_source:
            query = query.where(User.auth_source == auth_source)

        if is_admin is not None:
            query = query.where(User.is_admin == is_admin)

        if is_active is not None:
            query = query.where(User.is_active == is_active)

        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    User.username.ilike(search_term),
                    User.email.ilike(search_term),
                    User.service_name.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.execute(count_query)
        total_count = total.scalar()

        # Apply pagination
        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        users = result.scalars().all()

        return list(users), total_count

    async def create_user(
        self,
        data: UserCreate,
        created_by: Optional[User] = None
    ) -> Tuple[User, Optional[str]]:
        """
        Create a new user (human or service).

        Returns:
            (user, error_message)
        """
        # Check if username exists
        existing = await self.get_by_username(data.username)
        if existing:
            return None, "Username already exists"

        # Check if email exists (only if provided)
        if data.email:
            existing = await self.get_by_email(data.email)
            if existing:
                return None, "Email already exists"

        # Determine user type
        user_type = data.user_type if data.user_type else UserType.HUMAN

        # Create user
        user = User(
            username=data.username.lower(),
            email=data.email.lower() if data.email else None,
            password_hash=hash_password(data.password),
            user_type=user_type,
            is_admin=data.is_admin if user_type == UserType.HUMAN else False,
            # Read-only is orthogonal to admin (admin wins); it applies to any user type.
            is_readonly=data.is_readonly and not (data.is_admin if user_type == UserType.HUMAN else False),
            mfa_required=data.mfa_required if user_type == UserType.HUMAN else False,
            max_concurrent_connections=data.max_concurrent_connections,
            bandwidth_limit_mbps=data.bandwidth_limit_mbps,
            quota_monthly_gb=data.quota_monthly_gb,
            expires_at=data.expires_at,
            service_name=data.username.lower() if user_type == UserType.SERVICE else None,
            service_description=data.description,  # Use description for all user types
            allowed_source_ips=data.allowed_source_ips,  # Trusted Hosts (optional at creation)
            created_by_id=created_by.id if created_by else None
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        type_str = "Service account" if user_type == UserType.SERVICE else "User"
        logger.info(f"{type_str} created: {user.username} by {created_by.username if created_by else 'system'}")
        return user, None

    async def create_service_account(
        self,
        data: ServiceAccountCreate,
        created_by: User
    ) -> Tuple[Optional[User], Optional[str], Optional[str]]:
        """
        Create a new service account.

        Returns:
            (user, error_message, api_key)
        """
        # Generate username from service name
        username = f"svc_{data.service_name.lower()}"

        # Check if username exists
        existing = await self.get_by_username(username)
        if existing:
            return None, "Service account with this name already exists", None

        # Generate API key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)

        # Create service account
        user = User(
            username=username,
            password_hash=hash_password(api_key),  # Use API key as password too
            user_type=UserType.SERVICE,
            is_admin=data.is_admin,
            # Admin wins over read-only; never store both.
            is_readonly=data.is_readonly and not data.is_admin,
            service_name=data.service_name.lower(),
            service_description=data.service_description,
            api_key_hash=key_hash,
            allowed_source_ips=data.allowed_source_ips,
            max_concurrent_connections=data.max_concurrent_connections,
            bandwidth_limit_mbps=data.bandwidth_limit_mbps,
            expires_at=data.expires_at,
            created_by_id=created_by.id
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"Service account created: {user.username} by {created_by.username}")
        return user, None, api_key

    async def update_user(
        self,
        user: User,
        data: UserUpdate,
        updated_by: User
    ) -> Tuple[User, Optional[str]]:
        """
        Update user fields.

        Returns:
            (updated user, error_message)
        """
        update_data = data.model_dump(exclude_unset=True)

        # Check email uniqueness if being updated
        if "email" in update_data and update_data["email"]:
            existing = await self.get_by_email(update_data["email"])
            if existing and existing.id != user.id:
                return user, "Email already exists"
            update_data["email"] = update_data["email"].lower()

        # Normalize the admin/read-only pair: they are mutually exclusive and admin wins.
        # Whichever flag the update turns on forces the other off, so stored state can't drift.
        if update_data.get("is_admin") is True:
            update_data["is_readonly"] = False
        elif update_data.get("is_readonly") is True:
            update_data["is_admin"] = False

        # Apply updates
        for field, value in update_data.items():
            setattr(user, field, value)

        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"User updated: {user.username} by {updated_by.username}")
        return user, None

    async def delete_user(self, user: User, deleted_by: User) -> bool:
        """
        Delete a user (soft delete by deactivating).

        Returns:
            True if successful
        """
        # Don't allow deleting yourself
        if user.id == deleted_by.id:
            return False

        # Soft delete - just deactivate
        user.is_active = False
        await self.db.commit()

        logger.info(f"User deactivated: {user.username} by {deleted_by.username}")
        return True

    async def hard_delete_user(self, user: User, deleted_by: User) -> bool:
        """
        Permanently delete a user.

        Returns:
            True if successful
        """
        # Don't allow deleting yourself
        if user.id == deleted_by.id:
            return False

        await self.db.delete(user)
        await self.db.commit()

        logger.info(f"User permanently deleted: {user.username} by {deleted_by.username}")
        return True

    async def reset_password(self, user: User, new_password: str) -> bool:
        """
        Reset user's password (admin action).

        Returns:
            True if successful
        """
        user.password_hash = hash_password(new_password)
        await self.db.commit()

        logger.info(f"Password reset for user: {user.username}")
        return True

    async def regenerate_api_key(self, user: User) -> Tuple[Optional[str], Optional[str]]:
        """
        Regenerate API key for service account.

        Returns:
            (new_api_key, error_message)
        """
        if user.user_type != UserType.SERVICE:
            return None, "API keys can only be regenerated for service accounts"

        api_key = generate_api_key()
        user.api_key_hash = hash_api_key(api_key)
        user.password_hash = hash_password(api_key)
        await self.db.commit()

        logger.info(f"API key regenerated for service account: {user.username}")
        return api_key, None

    async def count_active_admins(self) -> int:
        """Count active users with is_admin=True"""
        result = await self.db.execute(
            select(func.count(User.id)).where(
                User.is_admin == True,
                User.is_active == True
            )
        )
        return result.scalar() or 0

    async def get_user_stats(self) -> dict:
        """Get user statistics"""
        # Total users
        total_result = await self.db.execute(select(func.count(User.id)))
        total = total_result.scalar()

        # Active users
        active_result = await self.db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        active = active_result.scalar()

        # By type
        human_result = await self.db.execute(
            select(func.count(User.id)).where(User.user_type == UserType.HUMAN)
        )
        human_count = human_result.scalar()

        service_result = await self.db.execute(
            select(func.count(User.id)).where(User.user_type == UserType.SERVICE)
        )
        service_count = service_result.scalar()

        # With MFA enabled
        mfa_result = await self.db.execute(
            select(func.count(User.id)).where(User.mfa_enabled == True)
        )
        mfa_enabled = mfa_result.scalar()

        return {
            "total_users": total,
            "active_users": active,
            "human_users": human_count,
            "service_accounts": service_count,
            "mfa_enabled": mfa_enabled,
        }
