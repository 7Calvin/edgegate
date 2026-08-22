"""
Schemas for the host-as-NAT-gateway settings (admin-managed).
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class NatGatewayUpdate(BaseModel):
    """Payload to create/update the single NAT gateway settings row."""
    enabled: bool = False
    network: Optional[str] = Field(None, max_length=64)
    public_interface: Optional[str] = Field(None, max_length=50)
    exclude_networks: Optional[str] = None


class NatGatewayResponse(BaseModel):
    """NAT gateway settings as returned to the UI."""
    enabled: bool = False
    network: Optional[str] = None
    public_interface: Optional[str] = None
    exclude_networks: Optional[str] = None
    # Remote subnets of enabled IPsec tunnels, auto-excluded from masquerade
    # (read-only — the user never types these).
    auto_excludes: List[str] = Field(default_factory=list)
    # Populated on PUT: whether the nat-agent (re)applied the rules.
    applied: Optional[bool] = None
    agent_message: Optional[str] = None
