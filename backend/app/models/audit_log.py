"""
Audit Log Model
"""
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class AuditLog(Base):
    """Audit Log - complete audit trail"""

    __tablename__ = "audit_logs"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Who (user_id can be NULL if user is deleted)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True
    )
    username = Column(String(50))  # Denormalized for safety

    # What
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50))
    resource_id = Column(UUID(as_uuid=True))

    # Details (JSON for flexibility)
    details = Column(JSONB)

    # Where
    ip_address = Column(INET, index=True)
    user_agent = Column(Text)

    # When
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    # Severity
    severity = Column(String(20), default="info")  # debug, info, warning, error, critical

    # Relationships
    user = relationship("User", back_populates="audit_logs")

    # Partitioning hint (PostgreSQL)
    __table_args__ = (
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    def __repr__(self):
        return f"<AuditLog {self.action} by {self.username} at {self.created_at}>"

    @classmethod
    def log_action(
        cls,
        session,
        user_id: uuid.UUID,
        username: str,
        action: str,
        resource_type: str = None,
        resource_id: uuid.UUID = None,
        details: dict = None,
        ip_address: str = None,
        user_agent: str = None,
        severity: str = "info"
    ):
        """Helper method to create audit log entry"""
        log = cls(
            user_id=user_id,
            username=username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            severity=severity
        )
        session.add(log)
        return log
