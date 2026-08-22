"""
Security utilities - Password hashing, JWT, MFA
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
import pyotp
import qrcode
import qrcode.image.svg
from io import BytesIO
import base64
import secrets
import hashlib

from app.core.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ==================== Password Functions ====================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> tuple[bool, list[str]]:
    """
    Validate password meets security requirements

    Returns:
        (is_valid, list_of_errors)
    """
    errors = []

    if len(password) < settings.MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {settings.MIN_PASSWORD_LENGTH} characters long")

    if settings.PASSWORD_REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")

    if settings.PASSWORD_REQUIRE_LOWERCASE and not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")

    if settings.PASSWORD_REQUIRE_NUMBERS and not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one number")

    if settings.PASSWORD_REQUIRE_SPECIAL:
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        if not any(c in special_chars for c in password):
            errors.append(f"Password must contain at least one special character: {special_chars}")

    return (len(errors) == 0, errors)


# ==================== JWT Functions ====================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT access token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None


# ==================== MFA/2FA Functions ====================

def generate_mfa_secret() -> str:
    """Generate a new MFA secret"""
    return pyotp.random_base32()


def generate_mfa_qr_code(username: str, secret: str) -> str:
    """
    Generate QR code for MFA setup

    Returns:
        Base64 encoded SVG image
    """
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=username,
        issuer_name=settings.MFA_ISSUER_NAME
    )

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    # Create image
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to base64
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{img_str}"


def verify_mfa_token(secret: str, token: str) -> bool:
    """
    Verify MFA/2FA token

    Args:
        secret: User's MFA secret
        token: 6-digit code from authenticator app

    Returns:
        True if valid, False otherwise
    """
    totp = pyotp.TOTP(secret)
    # valid_window=1 allows for time drift (±30 seconds)
    return totp.verify(token, valid_window=1)


def generate_backup_codes(count: int = 10) -> list[str]:
    """
    Generate backup codes for MFA recovery

    Returns:
        List of backup codes (format: XXXX-XXXX-XXXX)
    """
    codes = []
    for _ in range(count):
        code = secrets.token_hex(6).upper()
        formatted = f"{code[:4]}-{code[4:8]}-{code[8:12]}"
        codes.append(formatted)
    return codes


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage"""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_backup_code(code: str, hashed_code: str) -> bool:
    """Verify a backup code against stored hash"""
    return hash_backup_code(code) == hashed_code


# ==================== API Key Functions ====================

def generate_api_key() -> str:
    """Generate a secure API key for service accounts"""
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """Verify API key against stored hash"""
    return hash_api_key(api_key) == hashed_key


# ==================== Session Token ====================

def generate_session_token() -> str:
    """Generate a random session token"""
    return secrets.token_urlsafe(32)


# ==================== Password Reset Token ====================

def generate_reset_token(user_id: str) -> str:
    """Generate password reset token"""
    data = {
        "user_id": user_id,
        "type": "password_reset"
    }
    # Short expiration for reset tokens (1 hour)
    expires = timedelta(hours=1)
    return create_access_token(data, expires)


def verify_reset_token(token: str) -> Optional[str]:
    """Verify password reset token and return user_id"""
    payload = decode_token(token)
    if not payload or payload.get("type") != "password_reset":
        return None
    return payload.get("user_id")
