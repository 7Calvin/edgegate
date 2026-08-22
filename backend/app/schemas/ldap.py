"""
Schemas for LDAP / Active Directory settings (admin-managed).
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class LdapSettingsUpdate(BaseModel):
    """Payload to create/update the single LDAP settings row."""
    enabled: bool = False
    server: Optional[str] = Field(None, max_length=255)
    port: int = Field(389, ge=1, le=65535)
    use_ntlm: bool = True
    ad_domain: Optional[str] = Field(None, max_length=100)
    bind_dn: Optional[str] = Field(None, max_length=500)
    # Omit or send empty to keep the currently stored password unchanged.
    bind_password: Optional[str] = None
    search_base: Optional[str] = Field(None, max_length=500)
    user_attr: str = Field("sAMAccountName", max_length=50)
    required_group_dn: Optional[str] = Field(None, max_length=500)
    timeout: int = Field(5, ge=1, le=60)


class LdapSettingsResponse(BaseModel):
    """LDAP settings as returned to the UI. Never exposes the bind password."""
    enabled: bool
    server: Optional[str] = None
    port: int = 389
    use_ntlm: bool = True
    ad_domain: Optional[str] = None
    bind_dn: Optional[str] = None
    bind_password_set: bool = False
    search_base: Optional[str] = None
    user_attr: str = "sAMAccountName"
    required_group_dn: Optional[str] = None
    timeout: int = 5


class LdapTestRequest(BaseModel):
    """Candidate config to validate before saving (Test connection button)."""
    server: Optional[str] = Field(None, max_length=255)
    port: int = Field(389, ge=1, le=65535)
    use_ntlm: bool = True
    ad_domain: Optional[str] = Field(None, max_length=100)
    bind_dn: Optional[str] = Field(None, max_length=500)
    bind_password: Optional[str] = None  # falls back to the stored password if omitted
    search_base: Optional[str] = Field(None, max_length=500)
    timeout: int = Field(5, ge=1, le=60)


class LdapTestResponse(BaseModel):
    success: bool
    message: Optional[str] = None


class LdapSyncResponse(BaseModel):
    """Result of a group-sync run (mirror AD group -> local shadow users)."""
    success: bool
    message: Optional[str] = None
    dry_run: bool = False
    delete_mode: str = "deactivate"
    total_in_group: int = 0
    added: int = 0
    removed: int = 0
    reactivated: int = 0
    skipped: int = 0
    added_users: List[str] = Field(default_factory=list)
    removed_users: List[str] = Field(default_factory=list)
