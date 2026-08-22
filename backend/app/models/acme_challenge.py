"""
ACME Challenge Model for Manual DNS-01 Certificate Issuance
"""
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text,
    ForeignKey, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.session import Base


class ACMEChallengeStatus(str, enum.Enum):
    """ACME challenge status"""
    PENDING = "pending"
    VERIFIED = "verified"
    ISSUED = "issued"
    FAILED = "failed"
    EXPIRED = "expired"


class ACMEChallenge(Base):
    """Manual DNS-01 ACME Challenge for SSL Certificate Issuance"""

    __tablename__ = "acme_challenges"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Association
    proxy_route_id = Column(
        UUID(as_uuid=True),
        ForeignKey("proxy_routes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Domain
    domain = Column(String(255), nullable=False, index=True)

    # Status
    status = Column(
        SQLEnum(
            ACMEChallengeStatus,
            name="acme_challenge_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ACMEChallengeStatus.PENDING,
        nullable=False,
        index=True,
    )

    # DNS challenge data
    txt_record_name = Column(String(255))
    txt_record_value = Column(String(255))

    # ACME protocol state (for resuming)
    acme_order_url = Column(Text)
    acme_challenge_url = Column(Text)
    acme_finalize_url = Column(Text)
    acme_key_thumbprint = Column(String(255))
    acme_token = Column(String(255))

    # Certificate data (once issued)
    certificate_pem = Column(Text)
    private_key_pem = Column(Text)

    # Error tracking
    error_message = Column(Text)

    # Expiration
    expires_at = Column(DateTime(timezone=True))

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationships
    proxy_route = relationship("ProxyRoute", foreign_keys=[proxy_route_id])
    created_by = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<ACMEChallenge {self.domain} ({self.status})>"
