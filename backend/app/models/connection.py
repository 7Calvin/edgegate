"""
Connection Model - Active and Historical VPN Connections
"""
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, ForeignKey,
    BigInteger, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from datetime import datetime

from app.db.session import Base


class ConnectionStatus(str, enum.Enum):
    """Connection status"""
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    BANNED = "banned"


class Connection(Base):
    """VPN Connection - tracks active and historical connections"""

    __tablename__ = "connections"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    vpn_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vpn_profiles.id", ondelete="CASCADE"),
        nullable=True  # Nullable for simplified mode (password-only auth)
    )

    # Connection info
    source_ip = Column(INET, nullable=False)  # Client's public IP
    vpn_ip = Column(INET, nullable=True)  # Assigned VPN IP (nullable for simplified mode)

    # Status
    status = Column(
        SQLEnum(ConnectionStatus, name="connection_status", values_callable=lambda x: [e.value for e in x]),
        default=ConnectionStatus.ACTIVE,
        index=True
    )

    # Timing
    connected_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )
    disconnected_at = Column(DateTime(timezone=True))

    # Duration (calculated at query time or when disconnecting)
    duration_seconds = Column(Integer)

    # Traffic statistics
    bytes_sent = Column(BigInteger, default=0)
    bytes_received = Column(BigInteger, default=0)
    packets_sent = Column(BigInteger, default=0)
    packets_received = Column(BigInteger, default=0)

    # Metadata
    client_version = Column(String(50))
    os_info = Column(String(100))
    disconnect_reason = Column(Text)

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="connections")
    vpn_profile = relationship("VPNProfile", back_populates="connections")

    # Indexes
    __table_args__ = (
        {"postgresql_partition_by": "RANGE (connected_at)"},  # Partitioning hint
    )

    def __repr__(self):
        return f"<Connection {self.vpn_ip} status={self.status}>"

    @property
    def is_active(self) -> bool:
        """Check if connection is currently active"""
        return self.status == ConnectionStatus.ACTIVE

    @property
    def total_traffic_bytes(self) -> int:
        """Total traffic in bytes"""
        return self.bytes_sent + self.bytes_received

    @property
    def total_traffic_mb(self) -> float:
        """Total traffic in MB"""
        return round(self.total_traffic_bytes / (1024**2), 2)

    def disconnect(self, reason: str = None):
        """Mark connection as disconnected"""
        self.status = ConnectionStatus.DISCONNECTED
        self.disconnected_at = datetime.now()
        if reason:
            self.disconnect_reason = reason
