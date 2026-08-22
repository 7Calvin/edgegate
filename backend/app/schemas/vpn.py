"""
VPN Profile schemas
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timedelta
from uuid import UUID
import ipaddress

from app.models.vpn_profile import AuthMethod
from app.core.config import settings


class VPNProfileBase(BaseModel):
    """Base VPN profile schema"""
    compression: bool = False
    tcp_mode: bool = False
    custom_port: Optional[int] = Field(None, ge=1, le=65535)
    session_timeout_minutes: Optional[int] = Field(None, ge=1)
    idle_timeout_minutes: int = Field(default=30, ge=1)
    max_bandwidth_mbps: Optional[int] = Field(None, ge=1)


class VPNProfileCreate(VPNProfileBase):
    """Schema for creating VPN profile"""
    user_id: UUID
    auth_method: AuthMethod = AuthMethod.CERTIFICATE
    allowed_networks: List[str] = []
    denied_networks: List[str] = []
    push_routes: List[str] = []
    push_dns_servers: List[str] = []
    push_dns_domains: List[str] = []

    @field_validator("allowed_networks", "denied_networks", "push_routes")
    @classmethod
    def validate_networks(cls, v):
        for network in v:
            try:
                ipaddress.ip_network(network, strict=False)
            except ValueError:
                raise ValueError(f"Invalid network: {network}")
        return v

    @field_validator("push_dns_servers")
    @classmethod
    def validate_dns_servers(cls, v):
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise ValueError(f"Invalid DNS server IP: {ip}")
        return v


class VPNProfileUpdate(BaseModel):
    """Schema for updating VPN profile"""
    compression: Optional[bool] = None
    tcp_mode: Optional[bool] = None
    custom_port: Optional[int] = Field(None, ge=1, le=65535)
    session_timeout_minutes: Optional[int] = Field(None, ge=1)
    idle_timeout_minutes: Optional[int] = Field(None, ge=1)
    max_bandwidth_mbps: Optional[int] = Field(None, ge=1)
    allowed_networks: Optional[List[str]] = None
    denied_networks: Optional[List[str]] = None
    push_routes: Optional[List[str]] = None
    push_dns_servers: Optional[List[str]] = None
    push_dns_domains: Optional[List[str]] = None
    is_active: Optional[bool] = None


class VPNProfileResponse(BaseModel):
    """VPN profile response"""
    id: UUID
    user_id: UUID
    assigned_ip: str
    assigned_ipv6: Optional[str] = None
    auth_method: AuthMethod
    compression: bool
    tcp_mode: bool
    custom_port: Optional[int] = None
    session_timeout_minutes: Optional[int] = None
    idle_timeout_minutes: Optional[int] = None
    max_bandwidth_mbps: Optional[int] = None
    allowed_networks: List[str] = []
    denied_networks: List[str] = []
    push_routes: List[str] = []
    push_dns_servers: List[str] = []
    push_dns_domains: List[str] = []
    is_active: bool
    is_revoked: bool
    total_connections: int
    total_bytes_sent: int
    total_bytes_received: int
    last_connection_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    certificate_expires_at: Optional[datetime] = None

    # Validators to convert INET types to strings
    @field_validator("assigned_ip", "assigned_ipv6", mode="before")
    @classmethod
    def convert_ip_to_string(cls, v):
        if v is None:
            return None
        return str(v)

    @field_validator("allowed_networks", "denied_networks", "push_routes", "push_dns_servers", mode="before")
    @classmethod
    def convert_ip_list_to_strings(cls, v):
        if v is None:
            return []
        return [str(ip) for ip in v]

    @model_validator(mode="after")
    def compute_certificate_expiry(self):
        """Calculate certificate expiration based on created_at + configured expire days"""
        if self.created_at and not self.certificate_expires_at:
            expire_days = settings.EASYRSA_CERT_EXPIRE
            self.certificate_expires_at = self.created_at + timedelta(days=expire_days)
        return self

    class Config:
        from_attributes = True


class VPNConfigResponse(BaseModel):
    """OpenVPN config file response"""
    filename: str
    content: str
    content_type: str = "application/x-openvpn-profile"


class CertificateInfo(BaseModel):
    """Certificate information"""
    common_name: str
    serial_number: str
    issued_at: datetime
    expires_at: datetime
    is_revoked: bool
    fingerprint: str


class VPNServerStatus(BaseModel):
    """VPN server status"""
    is_running: bool
    uptime_seconds: Optional[int]
    connected_clients: int
    total_bytes_in: int
    total_bytes_out: int
    version: Optional[str]


class IPPoolStatus(BaseModel):
    """IP pool status"""
    network: str
    total_ips: int
    assigned_ips: int
    available_ips: int
    utilization_percent: float


class VPNServerConfig(BaseModel):
    """VPN Server configuration"""
    server_host: str = Field(..., description="Public hostname or IP for clients to connect")
    server_port: int = Field(1194, ge=1, le=65535)
    protocol: str = Field("udp", pattern="^(udp|tcp)$")
    vpn_network: str = Field("10.8.0.0", description="VPN subnet network address")
    vpn_netmask: str = Field("255.255.255.0", description="VPN subnet mask")
    dns_servers: List[str] = Field(default=["8.8.8.8", "1.1.1.1"], description="DNS servers to push to clients")
    internal_dns_server: Optional[str] = Field(None, description="Internal DNS server reachable through the tunnel (split-DNS)")
    split_dns_domains: List[str] = Field(default=[], description="Domains resolved via the internal DNS through the tunnel (split-DNS)")
    push_routes: List[str] = Field(default=[], description="Routes to push to clients (CIDR format)")
    redirect_gateway: bool = Field(True, description="Force all client traffic through VPN tunnel")
    compression: bool = Field(False, description="Enable LZ4 compression")
    client_to_client: bool = Field(False, description="Allow clients to see each other")
    duplicate_cn: bool = Field(False, description="Allow multiple connections with same certificate")
    max_clients: int = Field(100, ge=1, le=10000, description="Maximum concurrent clients")
    keepalive_interval: int = Field(10, ge=1, le=300, description="Keepalive ping interval (seconds)")
    keepalive_timeout: int = Field(120, ge=10, le=600, description="Keepalive timeout (seconds)")
    # Metadata - indicates if network can be changed (only before first profile)
    network_editable: bool = Field(True, description="Whether VPN network can be changed")

    @field_validator("dns_servers")
    @classmethod
    def validate_dns_servers(cls, v):
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise ValueError(f"Invalid DNS server IP: {ip}")
        return v

    @field_validator("internal_dns_server")
    @classmethod
    def validate_internal_dns_server(cls, v):
        # Empty -> "" (persists a cleared value past the route's "is not None" merge guard)
        if v is None or not str(v).strip():
            return ""
        try:
            ipaddress.ip_address(str(v).strip())
        except ValueError:
            raise ValueError(f"Invalid internal DNS server IP: {v}")
        return str(v).strip()

    @field_validator("split_dns_domains")
    @classmethod
    def validate_split_dns_domains(cls, v):
        cleaned = []
        for d in v or []:
            d = str(d).strip().lstrip(".")
            if not d:
                continue
            if " " in d or "/" in d:
                raise ValueError(f"Invalid domain: {d}")
            cleaned.append(d)
        return cleaned

    @field_validator("push_routes")
    @classmethod
    def validate_push_routes(cls, v):
        for route in v:
            try:
                ipaddress.ip_network(route, strict=False)
            except ValueError:
                raise ValueError(f"Invalid route: {route}")
        return v

    @field_validator("vpn_network")
    @classmethod
    def validate_vpn_network(cls, v):
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid network address: {v}")
        return v


class VPNNetworkChangeRequest(BaseModel):
    """Disruptive VPN subnet change (reassigns every client IP + restarts OpenVPN)."""
    vpn_network: str
    vpn_netmask: str

    @field_validator("vpn_network")
    @classmethod
    def _valid_network(cls, v):
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Endereço de rede inválido: {v}")
        return v

    @field_validator("vpn_netmask")
    @classmethod
    def _valid_netmask(cls, v):
        try:
            ipaddress.ip_network(f"0.0.0.0/{v}", strict=False)
        except ValueError:
            raise ValueError(f"Máscara inválida: {v}")
        return v


class VPNServerConfigUpdate(BaseModel):
    """VPN Server configuration update (all fields optional)"""
    server_host: Optional[str] = None
    server_port: Optional[int] = Field(None, ge=1, le=65535)
    protocol: Optional[str] = Field(None, pattern="^(udp|tcp)$")
    vpn_network: Optional[str] = None
    vpn_netmask: Optional[str] = None
    dns_servers: Optional[List[str]] = None
    internal_dns_server: Optional[str] = None
    split_dns_domains: Optional[List[str]] = None
    push_routes: Optional[List[str]] = None
    redirect_gateway: Optional[bool] = None
    compression: Optional[bool] = None
    client_to_client: Optional[bool] = None
    duplicate_cn: Optional[bool] = None
    max_clients: Optional[int] = Field(None, ge=1, le=10000)
    keepalive_interval: Optional[int] = Field(None, ge=1, le=300)
    keepalive_timeout: Optional[int] = Field(None, ge=10, le=600)

    @field_validator("dns_servers")
    @classmethod
    def validate_dns_servers(cls, v):
        if v is None:
            return v
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise ValueError(f"Invalid DNS server IP: {ip}")
        return v

    @field_validator("internal_dns_server")
    @classmethod
    def validate_internal_dns_server(cls, v):
        if v is None:
            return v
        if not str(v).strip():
            return ""
        try:
            ipaddress.ip_address(str(v).strip())
        except ValueError:
            raise ValueError(f"Invalid internal DNS server IP: {v}")
        return str(v).strip()

    @field_validator("split_dns_domains")
    @classmethod
    def validate_split_dns_domains(cls, v):
        if v is None:
            return v
        cleaned = []
        for d in v:
            d = str(d).strip().lstrip(".")
            if not d:
                continue
            if " " in d or "/" in d:
                raise ValueError(f"Invalid domain: {d}")
            cleaned.append(d)
        return cleaned

    @field_validator("push_routes")
    @classmethod
    def validate_push_routes(cls, v):
        if v is None:
            return v
        for route in v:
            try:
                ipaddress.ip_network(route, strict=False)
            except ValueError:
                raise ValueError(f"Invalid route: {route}")
        return v
