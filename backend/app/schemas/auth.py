"""
Authentication schemas
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
import re


class LoginRequest(BaseModel):
    """Login request schema"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=1)
    mfa_code: Optional[str] = Field(None, min_length=6, max_length=6)

    @field_validator("mfa_code")
    @classmethod
    def validate_mfa_code(cls, v):
        if v is not None and not v.isdigit():
            raise ValueError("MFA code must contain only digits")
        return v


class LoginResponse(BaseModel):
    """Login response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    username: str
    is_admin: bool
    mfa_enabled: bool = False
    mfa_required: bool = False
    mfa_pending: bool = False  # True if MFA is required but not yet provided


class TokenResponse(BaseModel):
    """Token refresh response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Refresh token request"""
    refresh_token: str


class MFASetupResponse(BaseModel):
    """MFA setup response with QR code"""
    secret: str
    qr_code: str  # Base64 encoded image
    backup_codes: List[str]
    message: str = "Scan the QR code with your authenticator app"


class MFAVerifyRequest(BaseModel):
    """MFA verification request"""
    code: str = Field(..., min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        if not v.isdigit():
            raise ValueError("MFA code must contain only digits")
        return v


class MFADisableRequest(BaseModel):
    """MFA disable request - requires password confirmation"""
    password: str
    mfa_code: str = Field(..., min_length=6, max_length=6)


class PasswordChangeRequest(BaseModel):
    """Password change request"""
    current_password: str
    new_password: str = Field(..., min_length=12)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v

    @field_validator("new_password")
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


class PasswordResetRequest(BaseModel):
    """Password reset request (forgot password)"""
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation"""
    token: str
    new_password: str = Field(..., min_length=12)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class APIKeyResponse(BaseModel):
    """API key generation response"""
    api_key: str  # Only shown once!
    key_prefix: str  # First 8 chars for identification
    created_at: datetime
    message: str = "Store this API key securely. It will not be shown again."


class SessionInfo(BaseModel):
    """Current session information"""
    user_id: str
    username: str
    user_type: str
    is_admin: bool
    mfa_enabled: bool
    mfa_required: bool
    issued_at: datetime
    expires_at: datetime
