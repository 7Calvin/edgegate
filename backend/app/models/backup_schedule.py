"""
Scheduled SFTP backup — a focused module (not a generic automation framework).
A named schedule runs the full backup (DB dump + OpenVPN PKI) and uploads it to an
SFTP server at the configured daily times.
"""
from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class BackupSchedule(Base):
    __tablename__ = "backup_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Daily run times "HH:MM" in the server's local timezone.
    schedule_times = Column(JSONB, nullable=False, default=list)

    # SFTP destination. Password is stored plaintext (like the IPsec PSK / the
    # FortiGate cli-script model); it is masked in API responses.
    sftp_host = Column(String(255), nullable=False)
    sftp_port = Column(Integer, nullable=False, default=22)
    sftp_username = Column(String(255), nullable=False)
    sftp_password = Column(String(512), nullable=False, default="")
    remote_path = Column(String(512), nullable=False, default="/{name}/{hostname}-{datetime}.tar.gz")

    # Last run bookkeeping.
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=True)   # success | failed
    last_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), nullable=True)
