"""
Proxy Route Model for Traefik Reverse Proxy
"""
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Integer,
    ForeignKey, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.session import Base


class ProxyRouteStatus(str, enum.Enum):
    """Proxy route status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"


class SSLMode(str, enum.Enum):
    """SSL certificate mode"""
    LETSENCRYPT = "letsencrypt"
    LETSENCRYPT_DNS = "letsencrypt_dns"
    CUSTOM = "custom"
    NONE = "none"


class HealthCheckType(str, enum.Enum):
    """Health check type"""
    HTTP = "http"
    TCP = "tcp"
    NONE = "none"


class ProxyRoute(Base):
    """Reverse Proxy Route for Traefik"""

    __tablename__ = "proxy_routes"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Route identification
    name = Column(String(100), nullable=False, unique=True, index=True)
    hostname = Column(String(255), nullable=False, unique=True, index=True)
    backend_url = Column(String(500), nullable=False)

    # Path routing
    path_prefix = Column(String(255))
    strip_prefix = Column(Boolean, default=False)

    # SSL
    ssl_mode = Column(
        SQLEnum(SSLMode, name="ssl_mode", values_callable=lambda x: [e.value for e in x]),
        default=SSLMode.LETSENCRYPT
    )
    force_https = Column(Boolean, default=True)

    # Health check
    health_check_type = Column(
        SQLEnum(HealthCheckType, name="health_check_type", values_callable=lambda x: [e.value for e in x]),
        default=HealthCheckType.HTTP
    )
    health_check_path = Column(String(255), default="/")
    health_check_interval = Column(String(20), default="30s")

    # Proxy behavior
    pass_host_header = Column(Boolean, default=True)
    custom_request_headers = Column(Text)   # JSON
    custom_response_headers = Column(Text)  # JSON

    # Rate limiting
    rate_limit_average = Column(Integer)
    rate_limit_burst = Column(Integer)

    # Status
    status = Column(
        SQLEnum(ProxyRouteStatus, name="proxy_route_status", values_callable=lambda x: [e.value for e in x]),
        default=ProxyRouteStatus.PENDING
    )
    is_enabled = Column(Boolean, default=True, index=True)

    # Health monitoring
    last_health_check = Column(DateTime(timezone=True))
    last_health_status = Column(Boolean)
    last_error = Column(Text)

    # SSL certificate info
    ssl_certificate_expiry = Column(DateTime(timezone=True))
    ssl_certificate_issuer = Column(String(255))

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<ProxyRoute {self.name} ({self.hostname})>"
