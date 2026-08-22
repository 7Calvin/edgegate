"""
User Model
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Enum as SQLEnum,
    Text, CheckConstraint, ForeignKey, BigInteger, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
import ipaddress
import uuid
from datetime import datetime
from typing import Optional

from app.db.session import Base


class UserType(str, enum.Enum):
    """User type enumeration"""
    HUMAN = "human"
    SERVICE = "service"
    ADMIN = "admin"


class AuthSource(str, enum.Enum):
    """Where a user's credentials are validated."""
    LOCAL = "local"  # password stored/verified in this database
    AD = "ad"        # authenticated against Active Directory (LDAP)


class User(Base):
    """User model - supports both human users and service accounts"""

    __tablename__ = "users"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic info
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), index=True)
    # Nullable: AD-backed users have no local password (auth_source == 'ad').
    password_hash = Column(String(255))

    # User type and flags
    user_type = Column(
        SQLEnum(UserType, name="user_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserType.HUMAN
    )
    # Which credential store validates this user. AD users are auto-provisioned
    # (JIT) on first successful AD login so connections/quotas/firewall can attach.
    auth_source = Column(
        SQLEnum(AuthSource, name="auth_source", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=AuthSource.LOCAL,
    )
    is_active = Column(Boolean, default=True, index=True)
    is_admin = Column(Boolean, default=False)

    # MFA/2FA - OPTIONAL controlled by admin
    mfa_required = Column(Boolean, default=False, nullable=False)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret = Column(String(32))
    mfa_backup_codes = Column(ARRAY(Text), default=[])

    # Service Account specific
    service_name = Column(String(100))
    service_description = Column(Text)
    api_key_hash = Column(String(64), index=True)
    allowed_source_ips = Column(ARRAY(INET), default=[])

    # Limits and quotas
    max_concurrent_connections = Column(Integer, default=1)
    bandwidth_limit_mbps = Column(Integer)
    quota_monthly_gb = Column(Integer)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    expires_at = Column(DateTime(timezone=True))
    last_login_at = Column(DateTime(timezone=True))
    last_login_ip = Column(INET)

    # Audit
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationships
    vpn_profile = relationship(
        "VPNProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="VPNProfile.user_id"
    )
    connections = relationship(
        "Connection",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Connection.user_id"
    )
    firewall_rules = relationship(
        "FirewallRule",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="FirewallRule.user_id"
    )
    audit_logs = relationship(
        "AuditLog",
        foreign_keys="AuditLog.user_id",
        back_populates="user"
    )

    # Self-referential relationship for created_by
    created_by = relationship("User", remote_side=[id])

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "user_type != 'service' OR service_name IS NOT NULL",
            name="valid_service_name"
        ),
        CheckConstraint(
            "NOT (mfa_enabled AND mfa_secret IS NULL)",
            name="valid_mfa"
        ),
    )

    def __repr__(self):
        return f"<User {self.username} ({self.user_type})>"

    @property
    def requires_mfa_on_login(self) -> bool:
        """Check if MFA is required for login"""
        if self.user_type == UserType.SERVICE:
            return False
        return self.mfa_required and self.mfa_enabled

    @property
    def is_service_account(self) -> bool:
        """Check if this is a service account"""
        return self.user_type == UserType.SERVICE

    @property
    def is_ad_user(self) -> bool:
        """Check if this user authenticates against Active Directory"""
        return self.auth_source == AuthSource.AD

    @property
    def is_expired(self) -> bool:
        """Check if account is expired"""
        if not self.expires_at:
            return False
        return datetime.now() > self.expires_at

    @property
    def is_subject_to_trusted_hosts(self) -> bool:
        """Trusted Hosts apply to panel/API principals only.

        Admins and service accounts (API keys) are restricted by their source-IP
        allowlist. Plain VPN users (human, non-admin) authenticate to the tunnel,
        not the console, and are intentionally exempt.
        """
        return bool(self.is_admin or self.is_service_account)

    def is_source_ip_trusted(self, source_ip: Optional[str]) -> bool:
        """Trusted Hosts check: is ``source_ip`` allowed to authenticate as this user?

        Supports IPv4/IPv6 hosts and CIDR ranges. An empty allowlist means no
        restriction. For a restricted account whose source IP cannot be resolved,
        we fail closed (deny) — recovery is via the local ``vpnctl`` CLI.
        """
        if not self.is_subject_to_trusted_hosts:
            return True

        if not self.allowed_source_ips:
            return True

        if not source_ip:
            return False

        try:
            addr = ipaddress.ip_address(source_ip)
        except ValueError:
            return False

        for entry in self.allowed_source_ips:
            try:
                network = ipaddress.ip_network(str(entry), strict=False)
            except ValueError:
                continue
            if addr.version == network.version and addr in network:
                return True

        return False

    def can_connect_from_ip(self, source_ip: Optional[str]) -> bool:
        """Backward-compatible alias for the Trusted Hosts check."""
        return self.is_source_ip_trusted(source_ip)
