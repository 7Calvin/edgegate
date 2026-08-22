"""
IP Pool Model - Manage VPN IP addresses
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class IPPool(Base):
    """IP Pool - available IP addresses for VPN clients"""

    __tablename__ = "ip_pool"

    # Primary key (the IP itself)
    ip_address = Column(INET, primary_key=True)

    # Allocation
    is_allocated = Column(Boolean, default=False, index=True)
    allocated_to_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL")
    )
    allocated_at = Column(DateTime(timezone=True))

    # Reservation (for special IPs like gateway, broadcast)
    is_reserved = Column(Boolean, default=False)
    reserved_for = Column(String(100))  # "gateway", "broadcast", etc

    # Subnet management
    subnet_id = Column(UUID(as_uuid=True))  # For multiple VPN subnets

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    allocated_to = relationship("User")

    def __repr__(self):
        status = "allocated" if self.is_allocated else "free"
        if self.is_reserved:
            status = f"reserved ({self.reserved_for})"
        return f"<IPPool {self.ip_address} - {status}>"

    @property
    def is_available(self) -> bool:
        """Check if IP is available for allocation"""
        return not self.is_allocated and not self.is_reserved
