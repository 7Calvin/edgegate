"""
User schemas for request/response validation
"""
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr, field_validator
from datetime import datetime
from uuid import UUID
import re

from app.models.user import UserType, AuthSource


def _ips_to_str(v):
    """Coerce a list of IP/network values to strings for response serialization.

    asyncpg decodes Postgres INET into ipaddress objects (IPv4Address/IPv4Network/
    IPv4Interface), which Pydantic's ``List[str]`` rejects — breaking any response
    that carries a non-empty allowlist. Normalize them back to plain strings.
    """
    if not v:
        return []
    return [str(ip) for ip in v]


class UserBase(BaseModel):
    """Base user schema with common fields"""
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[EmailStr] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            raise ValueError("Username can only contain letters, numbers, dots, underscores and hyphens")
        return v.lower()


class UserCreate(UserBase):
    """Schema for creating a new user (human or service)"""
    password: str = Field(..., min_length=12)
    email: Optional[EmailStr] = None  # Optional for all users
    user_type: UserType = UserType.HUMAN
    is_admin: bool = False
    mfa_required: bool = False
    max_concurrent_connections: int = Field(default=1, ge=1, le=10)
    bandwidth_limit_mbps: Optional[int] = Field(None, ge=1, le=10000)
    quota_monthly_gb: Optional[int] = Field(None, ge=1)
    expires_at: Optional[datetime] = None
    description: Optional[str] = Field(None, max_length=500)  # Description for any user type
    allowed_source_ips: List[str] = Field(default=[])  # Trusted Hosts (optional; empty = no restriction)

    @field_validator("allowed_source_ips")
    @classmethod
    def _validate_allowed_ips(cls, v):
        return _validate_cidr_list(v)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        errors = []
        if len(v) < 12:
            errors.append("Password must be at least 12 characters")
        if not re.search(r"[A-Z]", v):
            errors.append("Password must contain uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("Password must contain lowercase letter")
        if not re.search(r"\d", v):
            errors.append("Password must contain a number")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", v):
            errors.append("Password must contain a special character")
        if errors:
            raise ValueError("; ".join(errors))
        return v


class UserUpdate(BaseModel):
    """Schema for updating a user"""
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    mfa_required: Optional[bool] = None
    max_concurrent_connections: Optional[int] = Field(None, ge=1, le=10)
    bandwidth_limit_mbps: Optional[int] = Field(None, ge=1, le=10000)
    quota_monthly_gb: Optional[int] = Field(None, ge=1)
    expires_at: Optional[datetime] = None


class UserResponse(BaseModel):
    """User response schema"""
    id: UUID
    username: str
    email: Optional[str]
    user_type: UserType
    auth_source: AuthSource = AuthSource.LOCAL
    is_active: bool
    is_admin: bool
    mfa_required: bool
    mfa_enabled: bool
    max_concurrent_connections: int
    bandwidth_limit_mbps: Optional[int]
    quota_monthly_gb: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    expires_at: Optional[datetime]
    last_login_at: Optional[datetime]
    allowed_source_ips: List[str] = []

    @field_validator("allowed_source_ips", mode="before")
    @classmethod
    def _coerce_ips(cls, v):
        return _ips_to_str(v)

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """User list item (less detail)"""
    id: UUID
    username: str
    email: Optional[str]
    user_type: UserType
    auth_source: AuthSource = AuthSource.LOCAL
    is_active: bool
    is_admin: bool
    mfa_enabled: bool
    mfa_required: bool
    last_login_at: Optional[datetime]
    created_at: datetime
    service_name: Optional[str] = None
    service_description: Optional[str] = None
    allowed_source_ips: List[str] = []

    @field_validator("allowed_source_ips", mode="before")
    @classmethod
    def _coerce_ips(cls, v):
        return _ips_to_str(v)

    class Config:
        from_attributes = True


def _validate_cidr_list(v: List[str]) -> List[str]:
    """Validate & normalize a list of IP/CIDR trusted-host entries."""
    import ipaddress
    normalized: List[str] = []
    for raw in v:
        entry = raw.strip()
        if not entry:
            continue
        try:
            # Bare host -> normalize to /32 or /128 for consistent storage.
            addr = ipaddress.ip_address(entry)
            normalized.append(f"{addr}/{addr.max_prefixlen}")
            continue
        except ValueError:
            pass
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise ValueError(f"Invalid IP address or network: {entry}")
        normalized.append(str(network))
    return normalized


class TrustedHostsUpdate(BaseModel):
    """Replace the source-IP allowlist (Trusted Hosts) for a user."""
    allowed_source_ips: List[str] = Field(default=[])

    @field_validator("allowed_source_ips")
    @classmethod
    def validate_ips(cls, v):
        return _validate_cidr_list(v)


class TrustedHostsResponse(BaseModel):
    """Result of a Trusted Hosts update."""
    id: UUID
    username: str
    allowed_source_ips: List[str]

    @field_validator("allowed_source_ips", mode="before")
    @classmethod
    def _coerce_ips(cls, v):
        return _ips_to_str(v)

    class Config:
        from_attributes = True


class ServiceAccountCreate(BaseModel):
    """Schema for creating a service account"""
    service_name: str = Field(..., min_length=3, max_length=100)
    service_description: Optional[str] = Field(None, max_length=500)
    is_admin: bool = False
    allowed_source_ips: List[str] = Field(default=[])
    max_concurrent_connections: int = Field(default=5, ge=1, le=100)
    bandwidth_limit_mbps: Optional[int] = Field(None, ge=1, le=10000)
    expires_at: Optional[datetime] = None

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v):
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Service name can only contain letters, numbers, underscores and hyphens")
        return v.lower()

    @field_validator("allowed_source_ips")
    @classmethod
    def validate_ips(cls, v):
        import ipaddress
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError:
                    raise ValueError(f"Invalid IP address or network: {ip}")
        return v


class ServiceAccountResponse(BaseModel):
    """Service account response"""
    id: UUID
    username: str
    service_name: str
    service_description: Optional[str]
    user_type: UserType
    is_active: bool
    is_admin: bool
    allowed_source_ips: List[str]
    max_concurrent_connections: int
    bandwidth_limit_mbps: Optional[int]
    created_at: datetime
    expires_at: Optional[datetime]
    last_login_at: Optional[datetime]
    api_key_prefix: Optional[str] = None  # First 8 chars of API key
    api_key: Optional[str] = None  # Full key, returned only on creation

    @field_validator("allowed_source_ips", mode="before")
    @classmethod
    def _coerce_ips(cls, v):
        return _ips_to_str(v)

    class Config:
        from_attributes = True


class UserMeResponse(BaseModel):
    """Current user profile response"""
    id: UUID
    username: str
    email: Optional[str]
    user_type: UserType
    is_admin: bool
    mfa_required: bool
    mfa_enabled: bool
    max_concurrent_connections: int
    bandwidth_limit_mbps: Optional[int]
    quota_monthly_gb: Optional[int]
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True
