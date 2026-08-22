"""
Firewall Rule schemas
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from uuid import UUID
import ipaddress
import re

from app.models.firewall import FirewallAction, ProtocolType, NATType


class FirewallRuleBase(BaseModel):
    """Base firewall rule schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    action: FirewallAction
    protocol: ProtocolType = ProtocolType.ALL
    priority: int = Field(default=100, ge=1, le=10000)


class FirewallRuleCreate(FirewallRuleBase):
    """Schema for creating firewall rule"""
    user_id: Optional[UUID] = None  # NULL = global rule
    applies_to_service_accounts: bool = False
    applies_to_human_users: bool = False
    source_network: Optional[str] = None
    source_port_range: Optional[str] = None
    destination_network: Optional[str] = None
    destination_port_range: Optional[str] = None
    rate_limit_connections_per_second: Optional[int] = Field(None, ge=1, le=10000)

    @field_validator("source_network", "destination_network")
    @classmethod
    def validate_network(cls, v):
        if v is not None:
            try:
                ipaddress.ip_network(v, strict=False)
            except ValueError:
                raise ValueError(f"Invalid network: {v}")
        return v

    @field_validator("source_port_range", "destination_port_range")
    @classmethod
    def validate_port_range(cls, v):
        if v is None:
            return v
        # Valid formats: "80", "80,443", "1000-2000", "80,443,8080-8090"
        pattern = r'^(\d{1,5}(-\d{1,5})?)(,\d{1,5}(-\d{1,5})?)*$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid port range format: {v}")
        # Validate port numbers
        for part in v.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                if start > end or start < 1 or end > 65535:
                    raise ValueError(f"Invalid port range: {part}")
            else:
                port = int(part)
                if port < 1 or port > 65535:
                    raise ValueError(f"Invalid port: {port}")
        return v


class FirewallRuleUpdate(BaseModel):
    """Schema for updating firewall rule"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    action: Optional[FirewallAction] = None
    protocol: Optional[ProtocolType] = None
    priority: Optional[int] = Field(None, ge=1, le=10000)
    source_network: Optional[str] = None
    source_port_range: Optional[str] = None
    destination_network: Optional[str] = None
    destination_port_range: Optional[str] = None
    rate_limit_connections_per_second: Optional[int] = Field(None, ge=1, le=10000)
    is_active: Optional[bool] = None


class FirewallRuleResponse(BaseModel):
    """Firewall rule response"""
    id: UUID
    user_id: Optional[UUID]
    applies_to_service_accounts: bool
    applies_to_human_users: bool
    name: str
    description: Optional[str]
    action: FirewallAction
    protocol: ProtocolType
    priority: int
    source_network: Optional[str]
    source_port_range: Optional[str]
    destination_network: Optional[str]
    destination_port_range: Optional[str]
    rate_limit_connections_per_second: Optional[int]
    is_active: bool
    is_system_rule: bool
    created_at: datetime
    updated_at: Optional[datetime]
    created_by_id: Optional[UUID]

    @field_validator("source_network", "destination_network", mode="before")
    @classmethod
    def convert_network_to_string(cls, v):
        if v is None:
            return None
        return str(v)

    class Config:
        from_attributes = True


class FirewallRuleListResponse(BaseModel):
    """Firewall rule list item"""
    id: UUID
    user_id: Optional[UUID]
    name: str
    description: Optional[str] = None
    action: FirewallAction
    protocol: ProtocolType
    priority: int
    source_network: Optional[str] = None
    destination_network: Optional[str]
    destination_port_range: Optional[str]
    is_active: bool
    is_system_rule: bool

    @field_validator("source_network", "destination_network", mode="before")
    @classmethod
    def convert_network_to_string(cls, v):
        if v is None:
            return None
        return str(v)

    class Config:
        from_attributes = True


class FirewallStatus(BaseModel):
    """Firewall status"""
    engine: str  # nftables or iptables
    is_active: bool
    total_rules: int
    active_rules: int
    last_applied_at: Optional[datetime]


class NFTablesConfig(BaseModel):
    """NFTables configuration"""
    table_name: str = "vpn_filter"
    chain_name: str = "vpn_rules"
    rules: List[str]
    generated_at: datetime


# ==================== NAT Rule Schemas ====================

class NATRuleBase(BaseModel):
    """Base NAT rule schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    nat_type: NATType = NATType.DNAT
    protocol: ProtocolType = ProtocolType.TCP


class NATRuleCreate(NATRuleBase):
    """Schema for creating NAT rule"""
    external_port: int = Field(..., ge=1, le=65535)
    internal_ip: str
    internal_port: int = Field(..., ge=1, le=65535)
    source_network: Optional[str] = None

    @field_validator("internal_ip")
    @classmethod
    def validate_ip(cls, v):
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid IP address: {v}")
        return v

    @field_validator("source_network")
    @classmethod
    def validate_source_network(cls, v):
        if v is not None:
            for part in v.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    ipaddress.ip_network(part, strict=False)
                except ValueError:
                    try:
                        ipaddress.ip_address(part)
                    except ValueError:
                        raise ValueError(f"Invalid IP/CIDR: {part}")
        return v


class NATRuleUpdate(BaseModel):
    """Schema for updating NAT rule"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    protocol: Optional[ProtocolType] = None
    external_port: Optional[int] = Field(None, ge=1, le=65535)
    internal_ip: Optional[str] = None
    internal_port: Optional[int] = Field(None, ge=1, le=65535)
    source_network: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("source_network")
    @classmethod
    def validate_source_network(cls, v):
        if v is not None:
            for part in v.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    ipaddress.ip_network(part, strict=False)
                except ValueError:
                    try:
                        ipaddress.ip_address(part)
                    except ValueError:
                        raise ValueError(f"Invalid IP/CIDR: {part}")
        return v


class NATRuleResponse(BaseModel):
    """NAT rule response"""
    id: UUID
    name: str
    description: Optional[str]
    nat_type: NATType
    protocol: ProtocolType
    external_port: int
    internal_ip: str
    internal_port: int
    source_network: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    created_by_id: Optional[UUID]

    @field_validator("internal_ip", "source_network", mode="before")
    @classmethod
    def convert_to_string(cls, v):
        if v is None:
            return None
        return str(v)

    class Config:
        from_attributes = True
