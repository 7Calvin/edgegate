"""
VPN Profile Model
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Text,
    ForeignKey, BigInteger, ARRAY, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.session import Base


class AuthMethod(str, enum.Enum):
    """Authentication method for VPN"""
    PASSWORD = "password"
    API_KEY = "api_key"
    CERTIFICATE = "certificate"


class VPNProfile(Base):
    """VPN Profile - one per user"""

    __tablename__ = "vpn_profiles"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )

    # Certificates
    client_cert = Column(Text, nullable=False)
    client_key = Column(Text, nullable=False)
    ca_cert = Column(Text, nullable=False)
    ta_key = Column(Text)  # TLS-Auth key

    # Network configuration
    assigned_ip = Column(INET, unique=True, nullable=False, index=True)
    assigned_ipv6 = Column(INET)
    subnet_mask = Column(INET, default="255.255.255.0")

    # Authentication method
    auth_method = Column(
        SQLEnum(AuthMethod, name="auth_method", values_callable=lambda x: [e.value for e in x]),
        default=AuthMethod.PASSWORD
    )

    # Routes
    allowed_networks = Column(ARRAY(INET), default=[])
    denied_networks = Column(ARRAY(INET), default=[])
    push_routes = Column(ARRAY(INET), default=[])

    # DNS
    push_dns_servers = Column(ARRAY(INET), default=[])
    push_dns_domains = Column(ARRAY(Text), default=[])

    # Connection settings
    compression = Column(Boolean, default=False)
    tcp_mode = Column(Boolean, default=False)
    custom_port = Column(Integer)

    # Limits
    session_timeout_minutes = Column(Integer)
    idle_timeout_minutes = Column(Integer, default=30)
    max_bandwidth_mbps = Column(Integer)

    # Status
    is_active = Column(Boolean, default=True, index=True)
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime(timezone=True))
    revoked_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    revocation_reason = Column(Text)

    # Statistics (denormalized for performance)
    total_connections = Column(Integer, default=0)
    total_bytes_sent = Column(BigInteger, default=0)
    total_bytes_received = Column(BigInteger, default=0)
    last_connection_at = Column(DateTime(timezone=True))

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="vpn_profile", foreign_keys=[user_id])
    revoked_by = relationship("User", foreign_keys=[revoked_by_id])
    connections = relationship("Connection", back_populates="vpn_profile")

    def __repr__(self):
        return f"<VPNProfile {self.assigned_ip} for user_id={self.user_id}>"

    @property
    def total_traffic_bytes(self) -> int:
        """Total traffic in bytes"""
        return self.total_bytes_sent + self.total_bytes_received

    @property
    def total_traffic_gb(self) -> float:
        """Total traffic in GB"""
        return round(self.total_traffic_bytes / (1024**3), 2)
