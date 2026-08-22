"""
Proxy Route schemas for Traefik Reverse Proxy
"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from uuid import UUID
import re
import json

from app.models.proxy_route import ProxyRouteStatus, SSLMode, HealthCheckType


# Hostname regex (RFC 1123)
HOSTNAME_PATTERN = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*$'
)
INTERVAL_PATTERN = re.compile(r'^\d+[smh]$')


class ProxyRouteCreate(BaseModel):
    """Schema for creating a proxy route"""
    name: str = Field(..., min_length=1, max_length=100)
    hostname: str = Field(..., min_length=1, max_length=255)
    backend_url: str = Field(..., min_length=1, max_length=500)

    # Path routing
    path_prefix: Optional[str] = Field(None, max_length=255)
    strip_prefix: bool = False

    # SSL
    ssl_mode: SSLMode = SSLMode.LETSENCRYPT
    force_https: bool = True

    # Health check
    health_check_type: HealthCheckType = HealthCheckType.HTTP
    health_check_path: str = Field(default="/", max_length=255)
    health_check_interval: str = Field(default="30s", max_length=20)

    # Proxy behavior
    pass_host_header: bool = True
    custom_request_headers: Optional[str] = None
    custom_response_headers: Optional[str] = None

    # Rate limiting
    rate_limit_average: Optional[int] = Field(None, ge=1)
    rate_limit_burst: Optional[int] = Field(None, ge=1)

    # Control
    is_enabled: bool = True

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v):
        if not HOSTNAME_PATTERN.match(v):
            raise ValueError(f"Invalid hostname: {v}")
        return v.lower()

    @field_validator("backend_url")
    @classmethod
    def validate_backend_url(cls, v):
        if not v.startswith(("http://", "https://")):
            raise ValueError("Backend URL must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("health_check_interval")
    @classmethod
    def validate_interval(cls, v):
        if not INTERVAL_PATTERN.match(v):
            raise ValueError(f"Invalid interval format (use e.g., '30s', '1m', '1h'): {v}")
        return v

    @field_validator("custom_request_headers", "custom_response_headers")
    @classmethod
    def validate_headers_json(cls, v):
        if v is None:
            return v
        try:
            parsed = json.loads(v)
            if not isinstance(parsed, dict):
                raise ValueError("Headers must be a JSON object")
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for headers")
        return v


class ProxyRouteUpdate(BaseModel):
    """Schema for updating a proxy route"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    hostname: Optional[str] = Field(None, min_length=1, max_length=255)
    backend_url: Optional[str] = Field(None, min_length=1, max_length=500)

    path_prefix: Optional[str] = Field(None, max_length=255)
    strip_prefix: Optional[bool] = None

    ssl_mode: Optional[SSLMode] = None
    force_https: Optional[bool] = None

    health_check_type: Optional[HealthCheckType] = None
    health_check_path: Optional[str] = Field(None, max_length=255)
    health_check_interval: Optional[str] = Field(None, max_length=20)

    pass_host_header: Optional[bool] = None
    custom_request_headers: Optional[str] = None
    custom_response_headers: Optional[str] = None

    rate_limit_average: Optional[int] = Field(None, ge=1)
    rate_limit_burst: Optional[int] = Field(None, ge=1)

    is_enabled: Optional[bool] = None

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v):
        if v is None:
            return v
        if not HOSTNAME_PATTERN.match(v):
            raise ValueError(f"Invalid hostname: {v}")
        return v.lower()

    @field_validator("backend_url")
    @classmethod
    def validate_backend_url(cls, v):
        if v is None:
            return v
        if not v.startswith(("http://", "https://")):
            raise ValueError("Backend URL must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("health_check_interval")
    @classmethod
    def validate_interval(cls, v):
        if v is None:
            return v
        if not INTERVAL_PATTERN.match(v):
            raise ValueError(f"Invalid interval format (use e.g., '30s', '1m', '1h'): {v}")
        return v

    @field_validator("custom_request_headers", "custom_response_headers")
    @classmethod
    def validate_headers_json(cls, v):
        if v is None:
            return v
        try:
            parsed = json.loads(v)
            if not isinstance(parsed, dict):
                raise ValueError("Headers must be a JSON object")
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for headers")
        return v


class ProxyRouteResponse(BaseModel):
    """Proxy route response"""
    id: UUID
    name: str
    hostname: str
    backend_url: str

    path_prefix: Optional[str]
    strip_prefix: bool

    ssl_mode: SSLMode
    force_https: bool

    health_check_type: HealthCheckType
    health_check_path: Optional[str]
    health_check_interval: Optional[str]

    pass_host_header: bool
    custom_request_headers: Optional[str]
    custom_response_headers: Optional[str]

    rate_limit_average: Optional[int]
    rate_limit_burst: Optional[int]

    status: ProxyRouteStatus
    is_enabled: bool

    last_health_check: Optional[datetime]
    last_health_status: Optional[bool]
    last_error: Optional[str]

    ssl_certificate_expiry: Optional[datetime]
    ssl_certificate_issuer: Optional[str]

    created_at: datetime
    updated_at: Optional[datetime]
    created_by_id: Optional[UUID]

    class Config:
        from_attributes = True


class ProxyRouteListResponse(BaseModel):
    """Proxy route list item (full details for edit support)"""
    id: UUID
    name: str
    hostname: str
    backend_url: str

    path_prefix: Optional[str]
    strip_prefix: bool

    ssl_mode: SSLMode
    force_https: bool

    health_check_type: HealthCheckType
    health_check_path: Optional[str]
    health_check_interval: Optional[str]

    pass_host_header: bool
    custom_request_headers: Optional[str]
    custom_response_headers: Optional[str]

    rate_limit_average: Optional[int]
    rate_limit_burst: Optional[int]

    status: ProxyRouteStatus
    is_enabled: bool

    last_health_check: Optional[datetime]
    last_health_status: Optional[bool]
    last_error: Optional[str]

    ssl_certificate_expiry: Optional[datetime]
    ssl_certificate_issuer: Optional[str]

    created_at: datetime
    updated_at: Optional[datetime]
    created_by_id: Optional[UUID]

    class Config:
        from_attributes = True


class TraefikConfigPreview(BaseModel):
    """Preview of generated Traefik dynamic YAML"""
    yaml_config: str


class ProxyRouteHealthStatus(BaseModel):
    """Result of a health check"""
    route_id: UUID
    route_name: str
    hostname: str
    backend_url: str
    is_healthy: bool
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error: Optional[str] = None


class CertificateInfo(BaseModel):
    """SSL certificate information from Traefik ACME storage"""
    domain: str
    sans: list[str] = []
    issuer: Optional[str] = None
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    days_remaining: Optional[int] = None
    status: str  # valid, expiring, expired, error
    serial_number: Optional[str] = None
    fingerprint: Optional[str] = None


class CertificateListResponse(BaseModel):
    """List of all managed certificates"""
    certificates: list[CertificateInfo]
    acme_email: Optional[str] = None
    total: int
    valid: int
    expiring: int
    expired: int


class CertificateRenewResponse(BaseModel):
    """Response from certificate renewal"""
    success: bool
    message: str
    domain: str
