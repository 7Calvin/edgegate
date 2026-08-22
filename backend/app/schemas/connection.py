"""
Connection schemas
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID

from app.models.connection import ConnectionStatus


class ConnectionResponse(BaseModel):
    """Connection response"""
    id: UUID
    user_id: UUID
    vpn_profile_id: UUID
    source_ip: str
    vpn_ip: str
    status: ConnectionStatus
    connected_at: datetime
    disconnected_at: Optional[datetime]
    duration_seconds: Optional[int]
    bytes_sent: int
    bytes_received: int
    packets_sent: int
    packets_received: int
    client_version: Optional[str]
    os_info: Optional[str]
    disconnect_reason: Optional[str]

    class Config:
        from_attributes = True


class ConnectionListResponse(BaseModel):
    """Connection list item"""
    id: UUID
    user_id: UUID
    username: Optional[str] = None
    source_ip: str
    vpn_ip: str
    status: ConnectionStatus
    connected_at: datetime
    duration_seconds: Optional[int]
    bytes_sent: int
    bytes_received: int

    class Config:
        from_attributes = True


class ActiveConnectionResponse(BaseModel):
    """Active connection with user info"""
    id: UUID
    user_id: UUID
    username: str
    source_ip: str
    vpn_ip: str
    connected_at: datetime
    duration_seconds: int
    bytes_sent: int
    bytes_received: int
    client_version: Optional[str]
    os_info: Optional[str]

    class Config:
        from_attributes = True


class ConnectionStats(BaseModel):
    """Connection statistics"""
    total_connections: int
    active_connections: int
    active_users: int = 0
    connections_today: int
    connections_this_week: int
    connections_this_month: int
    unique_users_today: int
    peak_concurrent_today: int
    total_bytes_sent: int = 0
    total_bytes_received: int = 0


class BandwidthStats(BaseModel):
    """Bandwidth usage statistics"""
    period: str  # hour, day, week, month
    total_bytes_sent: int
    total_bytes_received: int
    average_bytes_per_connection: int
    peak_bandwidth_mbps: float
    data_points: List[dict]  # Time series data


class ThroughputPoint(BaseModel):
    """A single throughput sample (bytes transferred during one interval)"""
    timestamp: datetime
    bytes_sent: int      # server -> clients (download / "saída")
    bytes_received: int  # clients -> server (upload / "entrada")


class ThroughputResponse(BaseModel):
    """Throughput time-series for the dashboard chart"""
    window: str  # 1h, 6h, 24h, 7d
    source: str = "openvpn"  # openvpn | ipsec | total
    points: List[ThroughputPoint]


class UserConnectionStats(BaseModel):
    """Per-user connection statistics"""
    user_id: UUID
    username: str
    total_connections: int
    total_duration_seconds: int
    total_bytes_sent: int
    total_bytes_received: int
    last_connection_at: Optional[datetime]
    is_currently_connected: bool


class DisconnectRequest(BaseModel):
    """Request to disconnect a user"""
    reason: Optional[str] = Field(None, max_length=500)
    ban: bool = False  # If true, also ban the user temporarily
    ban_duration_minutes: Optional[int] = Field(None, ge=1, le=1440)  # Max 24 hours
