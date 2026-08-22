"""
Firewall Rules Model
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Text,
    ForeignKey, CheckConstraint, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.session import Base


class FirewallAction(str, enum.Enum):
    """Firewall action"""
    ACCEPT = "accept"
    DROP = "drop"
    REJECT = "reject"
    LIMIT = "limit"


class NATType(str, enum.Enum):
    """NAT rule type"""
    DNAT = "dnat"  # Destination NAT (port forwarding)
    SNAT = "snat"  # Source NAT


class ProtocolType(str, enum.Enum):
    """Network protocol"""
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    ALL = "all"


class FirewallRule(Base):
    """Firewall Rule - per-user or global"""

    __tablename__ = "firewall_rules"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Scope (NULL user_id = global rule)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    applies_to_service_accounts = Column(Boolean, default=False)
    applies_to_human_users = Column(Boolean, default=False)

    # Priority (lower number = higher priority)
    priority = Column(Integer, default=100, index=True)

    # Rule details
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # Action
    action = Column(
        SQLEnum(FirewallAction, name="firewall_action", values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )
    protocol = Column(
        SQLEnum(ProtocolType, name="protocol_type", values_callable=lambda x: [e.value for e in x]),
        default=ProtocolType.ALL
    )

    # Source (VPN clients)
    source_network = Column(INET)  # NULL = any
    source_port_range = Column(String(20))  # "80,443" or "1000-2000"

    # Destination (private network)
    destination_network = Column(INET)  # NULL = any
    destination_port_range = Column(String(20))

    # Rate limiting (for action = LIMIT)
    rate_limit_connections_per_second = Column(Integer)

    # Status
    is_active = Column(Boolean, default=True, index=True)
    is_system_rule = Column(Boolean, default=False)  # System rules can't be deleted

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationships
    user = relationship("User", back_populates="firewall_rules", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_id])

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR applies_to_service_accounts OR applies_to_human_users",
            name="valid_scope"
        ),
    )

    def __repr__(self):
        scope = "global" if not self.user_id else f"user:{self.user_id}"
        return f"<FirewallRule {self.name} ({scope}) priority={self.priority}>"

    @property
    def is_global(self) -> bool:
        """Check if this is a global rule"""
        return self.user_id is None

    def to_nftables_rule(self) -> str:
        """Convert to nftables syntax"""
        parts = []

        if self.source_network:
            parts.append(f"ip saddr {self.source_network}")

        if self.destination_network:
            parts.append(f"ip daddr {self.destination_network}")

        if self.protocol != ProtocolType.ALL:
            parts.append(self.protocol.value)

        if self.destination_port_range:
            parts.append(f"dport {self.destination_port_range}")

        parts.append(self.action.value)

        return " ".join(parts)


class NATRule(Base):
    """NAT Rule - DNAT/SNAT for port forwarding"""

    __tablename__ = "nat_rules"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Rule details
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # NAT type
    nat_type = Column(
        SQLEnum(NATType, name="nat_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=NATType.DNAT
    )

    # Protocol (reuse existing protocol_type enum)
    protocol = Column(
        SQLEnum(ProtocolType, name="protocol_type", values_callable=lambda x: [e.value for e in x], create_type=False),
        default=ProtocolType.TCP
    )

    # External (incoming)
    external_port = Column(Integer, nullable=False)

    # Internal (destination server)
    internal_ip = Column(INET, nullable=False)
    internal_port = Column(Integer, nullable=False)

    # Optional: restrict source (comma-separated IPs/CIDRs, or NULL = any)
    source_network = Column(Text)  # e.g. "10.0.0.1, 192.168.1.0/24"

    # Status
    is_active = Column(Boolean, default=True, index=True)

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
        return f"<NATRule {self.name} {self.external_port}->{self.internal_ip}:{self.internal_port}>"

    def to_nftables_rule(self) -> str:
        """Convert to nftables DNAT syntax"""
        parts = []

        if self.source_network:
            ips = [ip.strip() for ip in self.source_network.split(",") if ip.strip()]
            if len(ips) == 1:
                parts.append(f"ip saddr {ips[0]}")
            elif len(ips) > 1:
                parts.append("ip saddr { " + ", ".join(ips) + " }")

        parts.append(self.protocol.value)
        parts.append(f"dport {self.external_port}")
        parts.append(f"dnat to {self.internal_ip}:{self.internal_port}")

        return " ".join(parts)
