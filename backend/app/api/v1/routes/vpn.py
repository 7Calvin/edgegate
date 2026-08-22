"""
VPN Routes - Profiles, Certificates, Configs
"""
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.session import get_db
from app.models.user import User
from app.services.vpn_service import VPNService, get_server_config, save_server_config
from app.dependencies.auth import get_current_active_user, require_admin
from app.schemas.vpn import (
    VPNProfileCreate,
    VPNProfileUpdate,
    VPNProfileResponse,
    VPNConfigResponse,
    VPNServerStatus,
)
from app.schemas.common import MessageResponse
from app.core.config import settings

router = APIRouter()


@router.get("/profile", response_model=VPNProfileResponse)
async def get_my_vpn_profile(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's VPN profile"""
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_user_id(user.id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN profile not found. Contact administrator to create one."
        )

    return profile


@router.post("/profile", response_model=VPNProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_my_vpn_profile(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create VPN profile for current user.

    This generates certificates and assigns an IP address.
    """
    vpn_service = VPNService(db)

    # Create default profile
    data = VPNProfileCreate(user_id=user.id)
    profile, error = await vpn_service.create_profile(user, data)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    return profile


@router.get("/config")
async def download_vpn_config(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download .ovpn configuration file.

    Returns the OpenVPN client configuration file for the current user.
    """
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_user_id(user.id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN profile not found"
        )

    if not profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VPN profile is disabled"
        )

    if profile.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VPN certificate has been revoked"
        )

    config_content = await vpn_service.generate_ovpn_config(profile)

    return Response(
        content=config_content,
        media_type="application/x-openvpn-profile",
        headers={
            "Content-Disposition": f"attachment; filename={user.username}.ovpn"
        }
    )


@router.post("/certificate/regenerate", response_model=MessageResponse)
async def regenerate_certificate(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Regenerate VPN certificate for current user.

    This revokes the old certificate and generates a new one.
    The user will need to download a new .ovpn file.
    """
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_user_id(user.id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN profile not found"
        )

    # Revoke old certificate
    await vpn_service.revoke_profile(profile, user, reason="Certificate regeneration")

    # Re-fetch the profile after revoke (it was detached by the commit in revoke_profile)
    profile = await vpn_service.get_profile_by_user_id(user.id)

    # Delete old profile to allow creating a new one
    if profile:
        await db.delete(profile)
        await db.commit()

    # Create new profile
    data = VPNProfileCreate(user_id=user.id)
    new_profile, error = await vpn_service.create_profile(user, data)

    if error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate certificate: {error}"
        )

    return MessageResponse(message="Certificate regenerated successfully. Download your new .ovpn file.")


# ==================== Admin Routes ====================

@router.get("/profiles", response_model=list[VPNProfileResponse])
async def list_vpn_profiles(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """List all VPN profiles (admin only)"""
    from sqlalchemy import select
    from app.models.vpn_profile import VPNProfile

    result = await db.execute(
        select(VPNProfile).order_by(VPNProfile.created_at.desc())
    )
    profiles = result.scalars().all()

    return list(profiles)


@router.post("/profiles/{user_id}", response_model=VPNProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_vpn_profile_for_user(
    user_id: UUID,
    data: VPNProfileCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create VPN profile for a specific user (admin only)"""
    from sqlalchemy import select
    from app.models.user import User as UserModel

    # Get target user
    result = await db.execute(
        select(UserModel).where(UserModel.id == user_id)
    )
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    vpn_service = VPNService(db)
    data.user_id = user_id
    profile, error = await vpn_service.create_profile(target_user, data)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    return profile


@router.patch("/profiles/{profile_id}", response_model=VPNProfileResponse)
async def update_vpn_profile(
    profile_id: UUID,
    data: VPNProfileUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update VPN profile settings (admin only)"""
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_id(profile_id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN profile not found"
        )

    updated_profile = await vpn_service.update_profile(profile, data)
    return updated_profile


@router.post("/profiles/{profile_id}/revoke", response_model=MessageResponse)
async def revoke_vpn_profile(
    profile_id: UUID,
    reason: str = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Revoke VPN profile and certificate (admin only)"""
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_id(profile_id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN profile not found"
        )

    if profile.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile is already revoked"
        )

    success = await vpn_service.revoke_profile(profile, admin, reason)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke profile"
        )

    return MessageResponse(message="VPN profile revoked successfully")


@router.delete("/profiles/{profile_id}", response_model=MessageResponse)
async def delete_vpn_profile(
    profile_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete VPN profile permanently (admin only)"""
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_id(profile_id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN profile not found"
        )

    # Revoke certificate first if not already revoked
    if not profile.is_revoked:
        await vpn_service.revoke_profile(profile, admin, reason="Profile deleted by admin")
        # Re-fetch after revoke commit
        profile = await vpn_service.get_profile_by_id(profile_id)

    # Delete the profile
    if profile:
        await db.delete(profile)
        await db.commit()

    return MessageResponse(message="VPN profile deleted successfully")


@router.get("/server/status", response_model=VPNServerStatus)
async def get_vpn_server_status(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get OpenVPN server status (admin only)"""
    vpn_service = VPNService(db)
    status = await vpn_service.get_server_status()

    return VPNServerStatus(**status)


@router.post("/server/start", response_model=MessageResponse)
async def start_vpn_server(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Start OpenVPN server (admin only)"""
    vpn_service = VPNService(db)
    success, error = await vpn_service.start_server()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Failed to start server"
        )

    return MessageResponse(message="OpenVPN server started successfully")


@router.post("/server/stop", response_model=MessageResponse)
async def stop_vpn_server(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Stop OpenVPN server (admin only)"""
    vpn_service = VPNService(db)
    success, error = await vpn_service.stop_server()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Failed to stop server"
        )

    return MessageResponse(message="OpenVPN server stopped successfully")


@router.post("/server/restart", response_model=MessageResponse)
async def restart_vpn_server(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Restart OpenVPN server (admin only)"""
    vpn_service = VPNService(db)
    success, error = await vpn_service.restart_server()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Failed to restart server"
        )

    return MessageResponse(message="OpenVPN server restarted successfully")


@router.get("/server/connections")
async def get_active_connections(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get list of currently connected VPN clients (admin only)"""
    vpn_service = VPNService(db)
    connections = await vpn_service.get_active_connections()

    return {"connections": connections}


@router.post("/server/connections/{username}/disconnect", response_model=MessageResponse)
async def disconnect_vpn_client(
    username: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Disconnect a specific VPN client (admin only)"""
    vpn_service = VPNService(db)
    success, error = await vpn_service.disconnect_client(username)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Failed to disconnect client"
        )

    return MessageResponse(message=f"Client {username} disconnected successfully")


# ==================== Server Configuration Routes ====================

from app.schemas.vpn import VPNServerConfig, VPNServerConfigUpdate, VPNNetworkChangeRequest

# get_server_config / save_server_config are imported from app.services.vpn_service
# (single source of truth — see the import at the top of this module).


async def has_vpn_profiles(db: AsyncSession) -> bool:
    """Check if any VPN profiles exist"""
    from sqlalchemy import select, func
    from app.models.vpn_profile import VPNProfile
    result = await db.execute(select(func.count(VPNProfile.id)))
    count = result.scalar()
    return count > 0


@router.get("/server/config", response_model=VPNServerConfig)
async def get_vpn_server_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get VPN server configuration (admin only)"""
    config = get_server_config()
    # Check if network is editable (no profiles exist yet)
    config["network_editable"] = not await has_vpn_profiles(db)
    return VPNServerConfig(**config)


@router.put("/server/config", response_model=VPNServerConfig)
async def update_vpn_server_config(
    data: VPNServerConfigUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update VPN server configuration (admin only)

    Note: Some changes may require server restart to take effect.
    Network settings can only be changed before creating any VPN profiles.
    After saving, the server will automatically start if not running.
    """
    current_config = get_server_config()

    # Snapshot the values that drive server.conf so we only rewrite it / restart
    # OpenVPN when they actually change — a plain settings save (e.g. max_clients)
    # must not kick every connected client off.
    def _conf_keys(cfg: dict) -> dict:
        return {
            "redirect_gateway": cfg.get("redirect_gateway", True),
            "dns_servers": list(cfg.get("dns_servers", [])),
            "internal_dns_server": cfg.get("internal_dns_server", "") or "",
            "split_dns_domains": list(cfg.get("split_dns_domains", [])),
        }
    old_conf = _conf_keys(current_config)

    profiles_exist = await has_vpn_profiles(db)

    # Check if trying to change network when profiles exist
    if profiles_exist:
        if data.vpn_network is not None or data.vpn_netmask is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change VPN network after profiles have been created"
            )

    # Update only provided fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            current_config[key] = value

    if not save_server_config(current_config):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save configuration"
        )

    vpn_service = VPNService(db)
    import logging
    conf_changed = False

    # Apply server.conf changes only for values that actually changed.
    new_conf = _conf_keys(current_config)

    # redirect-gateway line
    if new_conf["redirect_gateway"] != old_conf["redirect_gateway"]:
        success, error = await vpn_service.update_server_conf_redirect_gateway(
            new_conf["redirect_gateway"]
        )
        if not success:
            logging.warning(f"Failed to update redirect-gateway: {error}")
        else:
            conf_changed = True

    # DNS / split-DNS push block. Depends on redirect_gateway too (full vs split
    # tunnel), so re-apply whenever any of these values changed. Deriving full vs
    # split from the effective redirect_gateway is what fixes the public-DNS-in-
    # split-tunnel bug.
    if new_conf != old_conf:
        success, error = await vpn_service.update_server_conf_dns(
            dns_servers=new_conf["dns_servers"],
            redirect_gateway=new_conf["redirect_gateway"],
            internal_dns_server=new_conf["internal_dns_server"],
            split_dns_domains=new_conf["split_dns_domains"],
        )
        if not success:
            logging.warning(f"Failed to update DNS push: {error}")
        else:
            conf_changed = True

    # Restart once if the running server config changed
    if conf_changed:
        server_status = await vpn_service.get_server_status()
        if server_status.get("is_running"):
            await vpn_service.restart_server()

    # Auto-start server if not running
    server_status = await vpn_service.get_server_status()
    if not server_status.get("is_running"):
        success, error = await vpn_service.start_server()
        if not success:
            import logging
            logging.warning(f"Failed to auto-start server: {error}")

    current_config["network_editable"] = not profiles_exist
    return VPNServerConfig(**current_config)


@router.put("/server/network", response_model=MessageResponse)
async def change_vpn_network_endpoint(
    data: VPNNetworkChangeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change the VPN subnet (DISRUPTIVE).

    Reassigns every client's tunnel IP, rewrites their ccd, and restarts OpenVPN.
    Allowed even after profiles exist — unlike the plain config update, which
    locks the network once profiles are created.
    """
    vpn_service = VPNService(db)
    ok, error = await vpn_service.change_vpn_network(data.vpn_network, data.vpn_netmask)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Falha ao alterar a rede da VPN",
        )
    return MessageResponse(
        message=f"Rede da VPN alterada para {data.vpn_network}/{data.vpn_netmask}. Os clientes precisam reconectar."
    )


# ==================== OpenVPN Integration Routes ====================
# These routes are called by OpenVPN scripts, not by users

from pydantic import BaseModel
from typing import Optional

class VPNAuthRequest(BaseModel):
    username: str
    password: str
    client_ip: Optional[str] = None

class VPNConnectRequest(BaseModel):
    username: str
    vpn_ip: str
    client_ip: str
    client_port: Optional[int] = None

class VPNDisconnectRequest(BaseModel):
    username: str
    vpn_ip: str
    bytes_sent: int = 0
    bytes_received: int = 0
    duration: int = 0


@router.get("/server/download")
async def download_server_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Download admin's .ovpn configuration file with full certificates.

    This config file includes the admin's client certificates for full VPN access.
    If the admin doesn't have a VPN profile yet, one will be created automatically.
    """
    vpn_service = VPNService(db)

    # Check if admin has a VPN profile
    profile = await vpn_service.get_profile_by_user_id(admin.id)

    # If admin doesn't have a profile, create one
    if not profile:
        data = VPNProfileCreate(user_id=admin.id)
        profile, error = await vpn_service.create_profile(admin, data)

        if error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create admin VPN profile: {error}"
            )

    # Check profile status
    if not profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VPN profile is disabled"
        )

    if profile.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VPN certificate has been revoked"
        )

    # Generate full .ovpn config with admin's certificates
    config_content = await vpn_service.generate_ovpn_config(profile)

    return Response(
        content=config_content,
        media_type="application/x-openvpn-profile",
        headers={
            "Content-Disposition": f"attachment; filename={admin.username}.ovpn"
        }
    )


@router.post("/auth")
async def vpn_authenticate(
    data: VPNAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    OpenVPN authentication endpoint.

    Called by auth-user-pass-verify script.
    Authenticates users by username/password only (no VPN profile required).
    """
    from app.services.auth_service import AuthService

    auth_service = AuthService(db)

    user, error, mfa_pending = await auth_service.authenticate_user(
        username=data.username,
        password=data.password,
        client_ip=data.client_ip
    )

    if error or mfa_pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error or "MFA required - use web interface"
        )

    # User authenticated successfully - no VPN profile required
    # Just check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    return {"success": True, "user_id": str(user.id)}


@router.post("/connections/connect")
async def vpn_client_connected(
    data: VPNConnectRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Called when a VPN client connects.

    Records the connection in the database.
    """
    from sqlalchemy import select, func
    from app.services.connection_service import ConnectionService
    from app.models.user import User as UserModel

    # Find user (case-insensitive: usernames are stored lowercased, but OpenVPN's
    # common_name — and AD's sAMAccountName — may arrive in mixed case).
    result = await db.execute(
        select(UserModel).where(func.lower(UserModel.username) == data.username.lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Get VPN profile (optional - may not exist in simplified mode)
    vpn_service = VPNService(db)
    profile = await vpn_service.get_profile_by_user_id(user.id)

    # Record connection
    connection_service = ConnectionService(db)
    connection, error = await connection_service.record_connection(
        user=user,
        vpn_profile=profile,  # Can be None in simplified mode
        source_ip=data.client_ip,
        vpn_ip=data.vpn_ip,  # OpenVPN-assigned IP; required so disconnect can match AD users
    )

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    return {"success": True, "connection_id": str(connection.id)}


@router.post("/connections/disconnect")
async def vpn_client_disconnected(
    data: VPNDisconnectRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Called when a VPN client disconnects.

    Updates connection statistics and marks as disconnected.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select, and_, cast
    from sqlalchemy.dialects.postgresql import INET
    from app.models.connection import Connection, ConnectionStatus

    # Find all active connections for this VPN IP (may have stale duplicates)
    result = await db.execute(
        select(Connection).where(
            and_(
                Connection.vpn_ip == cast(data.vpn_ip, INET),
                Connection.status == ConnectionStatus.ACTIVE
            )
        ).order_by(Connection.connected_at.desc())
    )
    connections = result.scalars().all()

    if not connections:
        # Connection might have been cleaned up already
        return {"success": True, "message": "No active connection found"}

    # Update the most recent connection with stats, mark all as disconnected
    for i, connection in enumerate(connections):
        if i == 0:
            # Most recent - update with actual stats
            connection.bytes_sent = data.bytes_sent
            connection.bytes_received = data.bytes_received
            connection.duration_seconds = data.duration
            connection.disconnect_reason = "Client disconnected"
        else:
            # Stale duplicates
            connection.disconnect_reason = "Stale connection cleanup"
        connection.status = ConnectionStatus.DISCONNECTED
        connection.disconnected_at = datetime.now(timezone.utc)

    await db.commit()

    return {"success": True}
