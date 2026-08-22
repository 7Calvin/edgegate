"""
IPsec Connection schemas for StrongSwan
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from uuid import UUID
import ipaddress
import re

from app.models.ipsec import IPsecStatus, IKEVersion, DPDAction


# Common cipher patterns
CIPHER_PATTERN = re.compile(r'^[a-z0-9\-]+$', re.IGNORECASE)
LIFETIME_PATTERN = re.compile(r'^\d+[smhd]$')


class IPsecConnectionBase(BaseModel):
    """Base IPsec connection schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class IPsecConnectionCreate(IPsecConnectionBase):
    """Schema for creating IPsec connection"""
    # Local (Left) - This server
    left_ip: str = Field(..., description="Private IP of this gateway")
    left_subnet: str = Field(..., description="Local network CIDR")
    left_id: str = Field(..., description="Public IP or FQDN of this gateway")

    # Remote (Right) - Peer
    right_ip: str = Field(..., description="Public IP of remote peer")
    right_ip_backup: Optional[str] = Field(None, description="2nd peer IP for HA/failover (remote_addrs)")
    right_subnet: str = Field(..., description="Remote network CIDR")
    right_id: str = Field(default="", description="ID of remote peer (defaults to right_ip if empty)")

    # Authentication
    auth_method: str = Field(default="psk", pattern=r'^(psk|pubkey)$')
    psk: Optional[str] = Field(None, min_length=8, max_length=256)

    # IKE Settings
    ike_version: IKEVersion = IKEVersion.IKEV2
    ike_cipher: str = Field(default="aes256-sha256-modp4096")
    ike_lifetime: str = Field(default="8h")

    # ESP Settings
    esp_cipher: str = Field(default="aes256-sha256-modp4096")
    key_lifetime: str = Field(default="1h")

    # Control
    auto_start: bool = True
    dpd_action: DPDAction = DPDAction.RESTART
    is_enabled: bool = True

    @field_validator("left_ip", "right_ip")
    @classmethod
    def validate_ip(cls, v):
        v = v.strip() if isinstance(v, str) else v  # tolerate pasted leading/trailing spaces
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid IP address: {v}")
        return v

    @field_validator("left_subnet", "right_subnet")
    @classmethod
    def validate_subnet(cls, v):
        """Validate subnet(s) - supports multiple subnets separated by comma"""
        # Split by comma and validate each subnet
        subnets = [s.strip() for s in v.split(',')]
        for subnet in subnets:
            try:
                ipaddress.ip_network(subnet, strict=False)
            except ValueError:
                raise ValueError(f"Invalid subnet: {subnet}")
        # Return normalized format (no extra spaces)
        return ','.join(subnets)

    @field_validator("left_id", "right_id")
    @classmethod
    def validate_id(cls, v):
        v = v.strip() if isinstance(v, str) else v  # tolerate pasted spaces
        # Empty is allowed — the config generator falls back to the peer IP.
        if not v:
            return v
        # ID can be IP address or FQDN
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        # Check if valid FQDN pattern
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]*[a-zA-Z0-9]$', v):
            raise ValueError(f"Invalid ID (must be IP or FQDN): {v}")
        return v

    @field_validator("right_ip_backup")
    @classmethod
    def validate_backup_ip(cls, v):
        v = v.strip() if isinstance(v, str) else v  # tolerate pasted spaces
        if not v:
            return v
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid backup IP address: {v}")
        return v

    @field_validator("ike_cipher", "esp_cipher")
    @classmethod
    def validate_cipher(cls, v):
        if not CIPHER_PATTERN.match(v):
            raise ValueError(f"Invalid cipher format: {v}")
        return v

    @field_validator("ike_lifetime", "key_lifetime")
    @classmethod
    def validate_lifetime(cls, v):
        if not LIFETIME_PATTERN.match(v):
            raise ValueError(f"Invalid lifetime format (use e.g., '8h', '1h', '30m'): {v}")
        return v


class IPsecConnectionUpdate(BaseModel):
    """Schema for updating IPsec connection"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None

    # Local (Left)
    left_ip: Optional[str] = None
    left_subnet: Optional[str] = None
    left_id: Optional[str] = None

    # Remote (Right)
    right_ip: Optional[str] = None
    right_ip_backup: Optional[str] = None
    right_subnet: Optional[str] = None
    right_id: Optional[str] = None

    # Authentication
    auth_method: Optional[str] = Field(None, pattern=r'^(psk|pubkey)$')
    psk: Optional[str] = Field(None, min_length=8, max_length=256)

    # IKE Settings
    ike_version: Optional[IKEVersion] = None
    ike_cipher: Optional[str] = None
    ike_lifetime: Optional[str] = None

    # ESP Settings
    esp_cipher: Optional[str] = None
    key_lifetime: Optional[str] = None

    # Control
    auto_start: Optional[bool] = None
    dpd_action: Optional[DPDAction] = None
    is_enabled: Optional[bool] = None

    @field_validator("left_ip", "right_ip")
    @classmethod
    def validate_ip(cls, v):
        if v is None:
            return v
        v = v.strip()  # tolerate pasted leading/trailing spaces
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid IP address: {v}")
        return v

    @field_validator("right_ip_backup")
    @classmethod
    def validate_backup_ip(cls, v):
        if v is None:
            return v
        v = v.strip()
        if v == "":
            return v  # empty clears the backup
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid backup IP address: {v}")
        return v

    @field_validator("left_id", "right_id")
    @classmethod
    def strip_id(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("left_subnet", "right_subnet")
    @classmethod
    def validate_subnet(cls, v):
        """Validate subnet(s) - supports multiple subnets separated by comma"""
        if v is None:
            return v
        # Split by comma and validate each subnet
        subnets = [s.strip() for s in v.split(',')]
        for subnet in subnets:
            try:
                ipaddress.ip_network(subnet, strict=False)
            except ValueError:
                raise ValueError(f"Invalid subnet: {subnet}")
        # Return normalized format (no extra spaces)
        return ','.join(subnets)


class IPsecConnectionResponse(BaseModel):
    """IPsec connection response"""
    id: UUID
    name: str
    description: Optional[str]

    # Local (Left)
    left_ip: str
    left_subnet: str
    left_id: str

    # Remote (Right)
    right_ip: str
    right_ip_backup: Optional[str] = None
    prefer_backup: bool = False
    right_subnet: str
    right_id: str

    # Authentication
    auth_method: str

    # IKE Settings
    ike_version: IKEVersion
    ike_cipher: str
    ike_lifetime: str

    # ESP Settings
    esp_cipher: str
    key_lifetime: str

    # Control
    auto_start: bool
    dpd_action: DPDAction

    # Status
    status: IPsecStatus
    is_enabled: bool
    last_status_check: Optional[datetime]
    last_error: Optional[str]

    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime]
    created_by_id: Optional[UUID]

    class Config:
        from_attributes = True


class IPsecConnectionListResponse(BaseModel):
    """IPsec connection list item"""
    id: UUID
    name: str
    description: Optional[str]
    left_ip: str
    left_subnet: str
    left_id: str
    right_ip: str
    right_ip_backup: Optional[str] = None
    prefer_backup: bool = False
    right_subnet: str
    right_id: str
    # Crypto settings — included so the edit form pre-fills with the saved values
    # (not the defaults). Without these, the frontend openEditModal falls back to
    # the default cipher and can overwrite the real value on save.
    auth_method: str
    ike_version: IKEVersion
    ike_cipher: str
    ike_lifetime: str
    esp_cipher: str
    key_lifetime: str
    dpd_action: DPDAction
    status: IPsecStatus
    is_enabled: bool
    auto_start: bool
    last_error: Optional[str]
    last_status_check: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class IPsecStatusResponse(BaseModel):
    """IPsec connection status from StrongSwan"""
    name: str
    status: str  # ESTABLISHED, CONNECTING, etc
    ike_status: Optional[str] = None  # IKE SA status
    tunnel_status: Optional[str] = None  # UP, DOWN, IKE_ONLY, CONNECTING
    has_child_sa: Optional[bool] = None  # Whether Child SA (ESP tunnel) is installed
    active_paths: Optional[int] = None  # HA/failover: how many endpoints have an SA up
    remote_host: Optional[str] = None  # HA/failover: the endpoint actually carrying traffic
    on_backup: Optional[bool] = None  # HA/failover: True = running on the backup (primary down)
    uptime: Optional[str] = None
    local_ts: Optional[str] = None  # Traffic selector
    remote_ts: Optional[str] = None
    bytes_in: Optional[int] = None
    bytes_out: Optional[int] = None
    rekey_time: Optional[str] = None
    error_hint: Optional[str] = None  # Hint about what might be wrong


class IPsecGlobalStatus(BaseModel):
    """Global IPsec status"""
    strongswan_running: bool
    total_connections: int
    active_tunnels: int
    connections: List[IPsecStatusResponse]


class IPsecConfigPreview(BaseModel):
    """Preview of generated IPsec configs"""
    ipsec_conf: str
    ipsec_secrets: str


class IPsecReloadResponse(BaseModel):
    """Response from config reload"""
    success: bool
    message: str
    output: Optional[str] = None
