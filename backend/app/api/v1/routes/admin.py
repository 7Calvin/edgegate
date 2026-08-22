"""
Admin Routes - System Administration
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.ldap_settings import LdapSettings
from app.models.nat_gateway_settings import NatGatewaySettings
from app.dependencies.auth import require_admin
from app.schemas.nat_gateway import NatGatewayUpdate, NatGatewayResponse
from app.schemas.common import MessageResponse
from app.schemas.ldap import (
    LdapSettingsUpdate,
    LdapSettingsResponse,
    LdapTestRequest,
    LdapTestResponse,
    LdapSyncResponse,
)

router = APIRouter()


def _ldap_to_response(cfg: Optional[LdapSettings]) -> LdapSettingsResponse:
    """Serialize LDAP settings for the UI (password write-only)."""
    if cfg is None:
        return LdapSettingsResponse(enabled=False)
    return LdapSettingsResponse(
        enabled=cfg.enabled,
        server=cfg.server,
        port=cfg.port,
        use_ntlm=cfg.use_ntlm,
        ad_domain=cfg.ad_domain,
        bind_dn=cfg.bind_dn,
        bind_password_set=bool(cfg.bind_password),
        search_base=cfg.search_base,
        user_attr=cfg.user_attr,
        required_group_dn=cfg.required_group_dn,
        timeout=cfg.timeout,
    )


@router.get("/dashboard")
async def get_admin_dashboard(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get admin dashboard summary"""
    # TODO: Implement dashboard aggregation
    return {
        "message": "Admin dashboard - to be implemented",
        "sections": [
            "user_stats",
            "connection_stats",
            "bandwidth_stats",
            "system_health"
        ]
    }


@router.get("/audit-logs")
async def get_audit_logs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[str] = None,
):
    """Audit trail (admin only) with filters + pagination."""
    from datetime import datetime
    from sqlalchemy import select, func, or_, desc
    from app.models.audit_log import AuditLog

    page = max(1, page)
    page_size = min(200, max(1, page_size))

    conds = []
    if category:
        conds.append(AuditLog.resource_type == category)
    if severity:
        conds.append(AuditLog.severity == severity)
    if search:
        s = f"%{search}%"
        conds.append(or_(AuditLog.action.ilike(s), AuditLog.username.ilike(s)))
    if since:
        try:
            conds.append(AuditLog.created_at >= datetime.fromisoformat(since))
        except ValueError:
            pass

    base = select(AuditLog)
    if conds:
        base = base.where(*conds)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (
        await db.execute(
            base.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    def ser(r: AuditLog) -> dict:
        return {
            "id": str(r.id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "username": r.username,
            "action": r.action,
            "resource_type": r.resource_type,
            "ip_address": str(r.ip_address) if r.ip_address else None,
            "severity": r.severity,
            "details": r.details,
        }

    return {"items": [ser(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/system/health")
async def get_system_health(
    admin: User = Depends(require_admin)
):
    """Get system health status"""
    # TODO: Implement comprehensive health check
    return {
        "status": "healthy",
        "services": {
            "database": "ok",
            "redis": "ok",
            "openvpn": "unknown",
            "firewall": "unknown"
        }
    }


@router.get("/system/config")
async def get_system_config(
    admin: User = Depends(require_admin)
):
    """Get current system configuration (sanitized)"""
    from app.core.config import settings

    # Return only safe configuration values
    return {
        "project_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "features": {
            "allow_registration": settings.FEATURE_ALLOW_USER_REGISTRATION,
            "enable_2fa": settings.FEATURE_ENABLE_2FA,
            "enable_api_keys": settings.FEATURE_ENABLE_API_KEYS,
            "enable_ldap": settings.FEATURE_ENABLE_LDAP,
        },
        "limits": {
            "max_users": settings.MAX_USERS,
            "max_service_accounts": settings.MAX_SERVICE_ACCOUNTS,
            "max_connections_per_user": settings.MAX_CONCURRENT_CONNECTIONS_PER_USER,
            "max_firewall_rules_per_user": settings.MAX_FIREWALL_RULES_PER_USER,
        },
        "vpn": {
            "network": settings.OPENVPN_NETWORK,
            "netmask": settings.OPENVPN_NETMASK,
            "protocol": settings.OPENVPN_PROTOCOL,
            "port": settings.OPENVPN_PORT,
        }
    }


@router.post("/system/maintenance")
async def toggle_maintenance_mode(
    enabled: bool,
    admin: User = Depends(require_admin)
):
    """Toggle maintenance mode (admin only)"""
    # TODO: Implement maintenance mode
    return {"message": f"Maintenance mode {'enabled' if enabled else 'disabled'} - to be implemented"}


@router.get("/ip-pools")
async def list_ip_pools(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """List IP address pools"""
    # TODO: Implement IP pool listing
    return {"message": "IP pools - to be implemented"}


@router.post("/ip-pools")
async def create_ip_pool(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create a new IP pool"""
    # TODO: Implement IP pool creation
    return {"message": "IP pool creation - to be implemented"}


@router.get("/network-routes")
async def list_network_routes(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """List network routes"""
    # TODO: Implement network routes listing
    return {"message": "Network routes - to be implemented"}


@router.post("/backup")
async def create_backup(
    admin: User = Depends(require_admin)
):
    """Create system backup"""
    # TODO: Implement backup functionality
    return {"message": "Backup creation - to be implemented"}


@router.get("/backups")
async def list_backups(
    admin: User = Depends(require_admin)
):
    """List available backups"""
    # TODO: Implement backup listing
    return {"message": "Backup list - to be implemented"}


# ==================== LDAP / Active Directory ====================

@router.get("/ldap-settings", response_model=LdapSettingsResponse)
async def get_ldap_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the current LDAP/AD configuration (bind password never exposed)."""
    from sqlalchemy import select

    cfg = (await db.execute(select(LdapSettings).limit(1))).scalar_one_or_none()
    return _ldap_to_response(cfg)


@router.put("/ldap-settings", response_model=LdapSettingsResponse)
async def update_ldap_settings(
    data: LdapSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the single LDAP/AD settings row (admin-only)."""
    from sqlalchemy import select

    cfg = (await db.execute(select(LdapSettings).limit(1))).scalar_one_or_none()
    if cfg is None:
        cfg = LdapSettings()
        db.add(cfg)

    cfg.enabled = data.enabled
    cfg.server = data.server
    cfg.port = data.port
    cfg.use_ntlm = data.use_ntlm
    cfg.ad_domain = data.ad_domain
    cfg.bind_dn = data.bind_dn
    cfg.search_base = data.search_base
    cfg.user_attr = data.user_attr
    cfg.required_group_dn = data.required_group_dn
    cfg.timeout = data.timeout
    # Only overwrite the password when a new non-empty value is provided.
    if data.bind_password:
        cfg.bind_password = data.bind_password

    await db.commit()
    await db.refresh(cfg)
    return _ldap_to_response(cfg)


@router.post("/ldap-settings/test", response_model=LdapTestResponse)
async def test_ldap_settings(
    data: LdapTestRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Validate a candidate LDAP config (service-account bind + base search)."""
    from sqlalchemy import select
    from app.services.ldap_service import LdapService

    # Fall back to the stored bind password if the form left it blank.
    bind_password = data.bind_password
    if not bind_password:
        cfg = (await db.execute(select(LdapSettings).limit(1))).scalar_one_or_none()
        bind_password = cfg.bind_password if cfg else None

    conf = {
        "server": data.server,
        "port": data.port,
        "use_ntlm": data.use_ntlm,
        "ad_domain": data.ad_domain,
        "bind_dn": data.bind_dn,
        "bind_password": bind_password,
        "search_base": data.search_base,
        "timeout": data.timeout,
    }
    ok, error = await LdapService(db).test_connection(conf)
    return LdapTestResponse(success=ok, message=error)


@router.post("/ldap-settings/sync-group", response_model=LdapSyncResponse)
async def sync_ldap_group(
    delete_mode: str = "deactivate",
    dry_run: bool = False,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mirror the AD group's members into local shadow users (admin-only).

    Query params:
      - delete_mode: how to treat AD users no longer in the group —
        "deactivate" (default, reversible) | "delete" (hard) | "keep".
      - dry_run: when true, computes counts without changing anything (preview).
    """
    from app.services.ldap_service import LdapService

    if delete_mode not in ("deactivate", "delete", "keep"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="delete_mode must be one of: deactivate, delete, keep",
        )
    result = await LdapService(db).sync_group(delete_mode=delete_mode, dry_run=dry_run)
    return LdapSyncResponse(**result)


# ==================== NAT Gateway (host-as-NAT) ====================

async def _ipsec_auto_excludes(db: AsyncSession) -> list:
    """Remote subnets of enabled IPsec tunnels — auto-excluded from masquerade."""
    from sqlalchemy import select
    from app.models.ipsec import IPsecConnection

    rows = (await db.execute(
        select(IPsecConnection.right_subnet).where(IPsecConnection.is_enabled.is_(True))
    )).scalars().all()
    out = []
    for val in rows:
        out += [s.strip() for s in (val or "").split(",") if s.strip()]
    return list(dict.fromkeys(out))


def _nat_gateway_to_response(cfg, auto_excludes=None, applied=None, agent_message=None) -> NatGatewayResponse:
    """Serialize NAT gateway settings; seed from env when no row exists yet."""
    from app.core.config import settings

    auto_excludes = auto_excludes or []
    if cfg is None:
        return NatGatewayResponse(
            enabled=bool(settings.NAT_GATEWAY_NETWORK),
            network=settings.NAT_GATEWAY_NETWORK or None,
            public_interface=settings.PUBLIC_INTERFACE or None,
            exclude_networks=getattr(settings, "NAT_GATEWAY_EXCLUDE", "") or None,
            auto_excludes=auto_excludes,
            applied=applied,
            agent_message=agent_message,
        )
    return NatGatewayResponse(
        enabled=cfg.enabled,
        network=cfg.network,
        public_interface=cfg.public_interface,
        exclude_networks=cfg.exclude_networks,
        auto_excludes=auto_excludes,
        applied=applied,
        agent_message=agent_message,
    )


@router.get("/nat-gateway", response_model=NatGatewayResponse)
async def get_nat_gateway(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the host-as-NAT-gateway config (DB row, or env defaults if unset)."""
    from sqlalchemy import select

    cfg = (await db.execute(select(NatGatewaySettings).limit(1))).scalar_one_or_none()
    return _nat_gateway_to_response(cfg, auto_excludes=await _ipsec_auto_excludes(db))


@router.put("/nat-gateway", response_model=NatGatewayResponse)
async def update_nat_gateway(
    data: NatGatewayUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Save the NAT gateway config and ask the agent to (re)apply it (admin-only)."""
    import ipaddress
    from sqlalchemy import select
    from app.api.v1.routes.firewall import apply_gateway_via_agent

    if data.enabled and not (data.network or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="network is required when the gateway is enabled",
        )
    if data.network:
        try:
            ipaddress.ip_network(data.network.strip(), strict=False)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid network CIDR: {data.network}",
            )
    for cidr in (data.exclude_networks or "").split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid exclude CIDR: {cidr}",
            )

    cfg = (await db.execute(select(NatGatewaySettings).limit(1))).scalar_one_or_none()
    if cfg is None:
        cfg = NatGatewaySettings()
        db.add(cfg)
    cfg.enabled = data.enabled
    cfg.network = (data.network or "").strip() or None
    cfg.public_interface = (data.public_interface or "").strip() or None
    cfg.exclude_networks = (data.exclude_networks or "").strip() or None
    await db.commit()
    await db.refresh(cfg)

    agent = await apply_gateway_via_agent()
    return _nat_gateway_to_response(
        cfg,
        auto_excludes=await _ipsec_auto_excludes(db),
        applied=bool(agent.get("success")),
        agent_message=agent.get("error"),
    )
