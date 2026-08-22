"""
Network Routes Model
"""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class NetworkRoute(Base):
    """Network Route - routing rules for VPN traffic"""

    __tablename__ = "network_routes"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Route details
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # Route configuration
    destination_network = Column(INET, nullable=False)
    gateway_ip = Column(INET)
    interface = Column(String(20))  # "eth0", "eth1", "tun0"
    metric = Column(Integer, default=100)

    # Application
    push_to_clients = Column(Boolean, default=False)
    applies_to_user_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])  # Empty = all users

    # Status
    is_active = Column(Boolean, default=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    def __repr__(self):
        return f"<NetworkRoute {self.name} to {self.destination_network}>"

    @property
    def applies_to_all_users(self) -> bool:
        """Check if route applies to all users"""
        return not self.applies_to_user_ids or len(self.applies_to_user_ids) == 0

    def to_openvpn_push(self) -> str:
        """Convert to OpenVPN push directive"""
        return f'push "route {self.destination_network}"'
