"""
LDAP / Active Directory settings.

Single-row table holding the runtime configuration for authenticating VPN users
against Active Directory. Managed entirely from the admin UI (not the .env) so an
admin can enable AD auth, point it at the DC and set the required VPN group without
restarting containers. When no row exists or `enabled` is false, the system runs
purely on the local user base (the default install behaviour).
"""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class LdapSettings(Base):
    """Runtime LDAP/AD configuration (single row, id fixed by convention)."""

    __tablename__ = "ldap_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Master toggle controlled from the frontend
    enabled = Column(Boolean, default=False, nullable=False)

    # Connection (plain LDAP 389 — no TLS)
    server = Column(String(255))          # host or IP of the Domain Controller
    port = Column(Integer, default=389, nullable=False)

    # Bind mechanism. Modern AD rejects unsigned simple binds over cleartext
    # ("strongerAuthRequired" / integrity required). NTLM performs a *signed*
    # bind over the same 389 port with no TLS and no AD changes — the same way
    # appliances like FortiGate authenticate. Kept configurable so directories
    # that still allow simple bind can use it.
    use_ntlm = Column(Boolean, default=True, nullable=False)
    ad_domain = Column(String(100))       # NetBIOS domain for NTLM, e.g. DOMAIN

    # Service account used to search the directory (bind then rebind as the user).
    # For NTLM: sAMAccountName ("seven") or DOMAIN\user ("DOMAIN\seven").
    # For simple bind: full DN ("CN=svc-vpn,OU=Service,DC=empresa,DC=com").
    bind_dn = Column(String(500))
    bind_password = Column(Text)          # write-only via API, never returned

    # Search scope
    search_base = Column(String(500))     # e.g. DC=empresa,DC=com
    user_attr = Column(String(50), default="sAMAccountName", nullable=False)

    # Group that grants VPN access. Nested membership is ALWAYS resolved
    # (LDAP_MATCHING_RULE_IN_CHAIN), so groups-inside-groups just work.
    required_group_dn = Column(String(500))  # e.g. CN=VPN-Users,OU=Groups,DC=empresa,DC=com

    # Network timeout for bind/search (seconds) — kept short so a slow/unreachable
    # DC never hangs the OpenVPN login.
    timeout = Column(Integer, default=5, nullable=False)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self):
        return f"<LdapSettings enabled={self.enabled} server={self.server}>"

    @property
    def is_active(self) -> bool:
        """True when AD auth should be attempted for unknown/AD users."""
        return bool(self.enabled and self.server and self.search_base and self.required_group_dn)
