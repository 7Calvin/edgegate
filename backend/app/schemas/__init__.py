"""
Pydantic Schemas for request/response validation
"""
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    ServiceAccountCreate,
    ServiceAccountResponse,
)
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    TokenResponse,
    RefreshTokenRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
)
from app.schemas.common import (
    MessageResponse,
    ErrorResponse,
    PaginationParams,
    PaginatedResponse,
)
from app.schemas.vpn import (
    VPNProfileCreate,
    VPNProfileUpdate,
    VPNProfileResponse,
    VPNConfigResponse,
    VPNServerStatus,
)
from app.schemas.firewall import (
    FirewallRuleCreate,
    FirewallRuleUpdate,
    FirewallRuleResponse,
    FirewallRuleListResponse,
    FirewallStatus,
)
from app.schemas.connection import (
    ConnectionResponse,
    ConnectionListResponse,
    ActiveConnectionResponse,
    ConnectionStats,
    BandwidthStats,
    DisconnectRequest,
)

__all__ = [
    # User schemas
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserListResponse",
    "ServiceAccountCreate",
    "ServiceAccountResponse",
    # Auth schemas
    "LoginRequest",
    "LoginResponse",
    "TokenResponse",
    "RefreshTokenRequest",
    "MFASetupResponse",
    "MFAVerifyRequest",
    "PasswordChangeRequest",
    "PasswordResetRequest",
    "PasswordResetConfirm",
    # Common schemas
    "MessageResponse",
    "ErrorResponse",
    "PaginationParams",
    "PaginatedResponse",
    # VPN schemas
    "VPNProfileCreate",
    "VPNProfileUpdate",
    "VPNProfileResponse",
    "VPNConfigResponse",
    "VPNServerStatus",
    # Firewall schemas
    "FirewallRuleCreate",
    "FirewallRuleUpdate",
    "FirewallRuleResponse",
    "FirewallRuleListResponse",
    "FirewallStatus",
    # Connection schemas
    "ConnectionResponse",
    "ConnectionListResponse",
    "ActiveConnectionResponse",
    "ConnectionStats",
    "BandwidthStats",
    "DisconnectRequest",
]
