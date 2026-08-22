"""
NAT gateway settings.

Single-row table holding the host-as-NAT-gateway configuration: which private
subnet is masqueraded to the internet through the public interface, and which
destinations are exempt (IPsec site-to-site). Managed from the admin UI so an
operator can change the gateway network without SSH or a redeploy. The nat-agent
reads this row on startup and whenever the backend calls its /gateway/apply
endpoint; the NAT_GATEWAY_* env vars remain a fallback for older deploys.
"""
from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class NatGatewaySettings(Base):
    """Runtime host-as-NAT-gateway configuration (single row)."""

    __tablename__ = "nat_gateway_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Master toggle. When false the agent installs no gateway masquerade.
    enabled = Column(Boolean, default=False, nullable=False)

    # Private subnet CIDR to masquerade to the internet, e.g. "10.1.0.0/16".
    network = Column(String(64))

    # Uplink interface toward the internet, e.g. "ens5".
    public_interface = Column(String(50))

    # Comma-separated CIDRs that must NOT be masqueraded (real source IP kept),
    # e.g. IPsec site-to-site peers like "192.168.3.0/24".
    exclude_networks = Column(Text)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self):
        return f"<NatGatewaySettings enabled={self.enabled} network={self.network}>"
