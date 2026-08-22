"""
Connections Routes - Active VPN Connections
"""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.connection import ConnectionStatus
from app.services.connection_service import ConnectionService
from app.dependencies.auth import get_current_active_user, require_admin
from app.schemas.connection import (
    ConnectionResponse,
    ConnectionListResponse,
    ActiveConnectionResponse,
    ConnectionStats,
    BandwidthStats,
    ThroughputResponse,
    UserConnectionStats,
    DisconnectRequest,
)
from app.schemas.common import MessageResponse, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[ConnectionListResponse])
async def list_connections(
    user_id: Optional[UUID] = None,
    status_filter: Optional[ConnectionStatus] = Query(None, alias="status"),
    active_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List VPN connections (admin only).

    Filter options:
    - user_id: Filter by specific user
    - status: Filter by connection status
    - active_only: Show only active connections
    """
    connection_service = ConnectionService(db)

    connections, total = await connection_service.list_connections(
        user_id=user_id,
        status=status_filter,
        active_only=active_only,
        skip=(page - 1) * per_page,
        limit=per_page
    )

    items = []
    for conn in connections:
        item = ConnectionListResponse(
            id=conn.id,
            user_id=conn.user_id,
            username=conn.user.username if conn.user else None,
            source_ip=str(conn.source_ip),
            vpn_ip=str(conn.vpn_ip),
            status=conn.status,
            connected_at=conn.connected_at,
            duration_seconds=conn.duration_seconds,
            bytes_sent=conn.bytes_sent,
            bytes_received=conn.bytes_received,
        )
        items.append(item)

    return PaginatedResponse.create(
        items=items,
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/active", response_model=list[ActiveConnectionResponse])
async def get_active_connections(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all currently active connections (admin only) with live data from OpenVPN"""
    from datetime import datetime, timezone
    connection_service = ConnectionService(db)

    # Get database connections
    connections = await connection_service.get_active_connections()

    # Get live data from OpenVPN
    live_connections = await connection_service.get_live_connections_from_server()

    # Create lookup by username for live data
    live_by_username = {lc["common_name"]: lc for lc in live_connections}

    result = []
    for conn in connections:
        username = conn.user.username if conn.user else "unknown"
        live_data = live_by_username.get(username, {})

        # Calculate duration from connected_at
        duration = 0
        if conn.connected_at:
            now = datetime.now(timezone.utc)
            connected = conn.connected_at if conn.connected_at.tzinfo else conn.connected_at.replace(tzinfo=timezone.utc)
            duration = int((now - connected).total_seconds())

        result.append(ActiveConnectionResponse(
            id=conn.id,
            user_id=conn.user_id,
            username=username,
            source_ip=str(conn.source_ip),
            vpn_ip=str(conn.vpn_ip),
            connected_at=conn.connected_at,
            duration_seconds=duration,
            bytes_sent=live_data.get("bytes_sent", conn.bytes_sent),
            bytes_received=live_data.get("bytes_received", conn.bytes_received),
            client_version=conn.client_version,
            os_info=conn.os_info,
        ))

    return result


@router.get("/live")
async def get_live_connections(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get live connection data from OpenVPN server (admin only).

    This queries the OpenVPN management interface directly
    for real-time connection information.
    """
    connection_service = ConnectionService(db)

    connections = await connection_service.get_live_connections_from_server()

    return {
        "count": len(connections),
        "connections": connections
    }


@router.get("/my", response_model=list[ConnectionListResponse])
async def get_my_connections(
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's connection history"""
    connection_service = ConnectionService(db)

    connections = await connection_service.get_user_connections(
        user_id=user.id,
        active_only=active_only,
        limit=limit
    )

    return [
        ConnectionListResponse(
            id=c.id,
            user_id=c.user_id,
            username=c.user.username if c.user else None,
            source_ip=str(c.source_ip),
            vpn_ip=str(c.vpn_ip),
            status=c.status,
            connected_at=c.connected_at,
            duration_seconds=c.duration_seconds,
            bytes_sent=c.bytes_sent,
            bytes_received=c.bytes_received,
        )
        for c in connections
    ]


@router.get("/my/active")
async def get_my_active_connections(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's active connections"""
    connection_service = ConnectionService(db)

    connections = await connection_service.get_user_connections(
        user_id=user.id,
        active_only=True
    )

    return {
        "count": len(connections),
        "max_allowed": user.max_concurrent_connections,
        "connections": [
            ConnectionListResponse(
                id=c.id,
                user_id=c.user_id,
                username=c.user.username if c.user else None,
                source_ip=str(c.source_ip),
                vpn_ip=str(c.vpn_ip),
                status=c.status,
                connected_at=c.connected_at,
                duration_seconds=c.duration_seconds,
                bytes_sent=c.bytes_sent,
                bytes_received=c.bytes_received,
            )
            for c in connections
        ]
    }


@router.get("/throughput", response_model=ThroughputResponse)
async def get_throughput(
    window: str = Query("24h", pattern="^(1h|6h|24h|7d)$"),
    source: str = Query("openvpn", pattern="^(openvpn|ipsec|total)$"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Bandwidth throughput time-series for the dashboard chart (admin only).

    Each point is the traffic transferred during one sampling interval,
    computed from periodic snapshots of the server-wide byte counters.
    ``source`` picks the technology: openvpn | ipsec | total.
    """
    connection_service = ConnectionService(db)

    data = await connection_service.get_throughput(window=window, source=source)

    return ThroughputResponse(**data)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get connection details (admin only)"""
    connection_service = ConnectionService(db)

    connection = await connection_service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )

    return connection


@router.post("/{connection_id}/disconnect", response_model=MessageResponse)
async def disconnect_connection(
    connection_id: UUID,
    data: DisconnectRequest = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Force disconnect a connection (admin only)"""
    connection_service = ConnectionService(db)

    connection = await connection_service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )

    if connection.status != ConnectionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection is not active"
        )

    reason = data.reason if data else "Disconnected by administrator"

    if data and data.ban:
        success = await connection_service.ban_connection(
            connection,
            reason=reason,
            ban_duration_minutes=data.ban_duration_minutes
        )
        message = "Connection banned"
    else:
        success = await connection_service.disconnect(
            connection,
            reason=reason,
            force=True
        )
        message = "Connection disconnected"

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect"
        )

    return MessageResponse(message=message)


@router.post("/user/{user_id}/disconnect", response_model=MessageResponse)
async def disconnect_user(
    user_id: UUID,
    reason: str = Query(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Disconnect all connections for a user (admin only)"""
    connection_service = ConnectionService(db)

    count = await connection_service.disconnect_user(
        user_id=user_id,
        reason=reason or "All connections disconnected by administrator"
    )

    return MessageResponse(message=f"Disconnected {count} connection(s)")


# ==================== Statistics ====================

@router.get("/stats/summary", response_model=ConnectionStats)
async def get_connection_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get connection statistics (admin only)"""
    connection_service = ConnectionService(db)

    stats = await connection_service.get_stats()

    return ConnectionStats(**stats)


@router.get("/stats/bandwidth", response_model=BandwidthStats)
async def get_bandwidth_stats(
    user_id: Optional[UUID] = None,
    period: str = Query("day", pattern="^(hour|day|week|month)$"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get bandwidth usage statistics (admin only)"""
    connection_service = ConnectionService(db)

    stats = await connection_service.get_bandwidth_stats(
        user_id=user_id,
        period=period
    )

    return BandwidthStats(**stats)


@router.get("/stats/user/{user_id}", response_model=UserConnectionStats)
async def get_user_connection_stats(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get connection statistics for a specific user (admin only)"""
    connection_service = ConnectionService(db)

    stats = await connection_service.get_user_stats(user_id)

    return UserConnectionStats(**stats)


@router.get("/my/stats", response_model=UserConnectionStats)
async def get_my_connection_stats(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's connection statistics"""
    connection_service = ConnectionService(db)

    stats = await connection_service.get_user_stats(user.id)

    return UserConnectionStats(**stats)


# ==================== Maintenance ====================

@router.post("/cleanup", response_model=MessageResponse)
async def cleanup_stale_connections(
    max_age_hours: int = Query(24, ge=1, le=168),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Clean up stale connections (admin only).

    Marks old active connections as disconnected.
    Useful for cleaning up orphaned records.
    """
    connection_service = ConnectionService(db)

    count = await connection_service.cleanup_stale_connections(max_age_hours)

    return MessageResponse(message=f"Cleaned up {count} stale connection(s)")
