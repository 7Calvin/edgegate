"""
IPsec Routes - StrongSwan Site-to-Site EdgeGate
"""
from typing import Optional
from uuid import UUID
import ipaddress
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.ipsec import IPsecStatus
from app.services.ipsec_service import IPsecService
from app.dependencies.auth import require_admin
from app.schemas.ipsec import (
    IPsecConnectionCreate,
    IPsecConnectionUpdate,
    IPsecConnectionResponse,
    IPsecConnectionListResponse,
    IPsecGlobalStatus,
    IPsecConfigPreview,
    IPsecReloadResponse,
)
from app.schemas.common import MessageResponse, PaginatedResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Connection CRUD ====================

@router.get("/connections", response_model=PaginatedResponse[IPsecConnectionListResponse])
async def list_ipsec_connections(
    is_enabled: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all IPsec connections (admin only).

    - Filter by is_enabled to see only active/inactive connections
    """
    service = IPsecService(db)

    connections, total = await service.list_connections(
        is_enabled=is_enabled,
        skip=(page - 1) * per_page,
        limit=per_page
    )

    return PaginatedResponse.create(
        items=[IPsecConnectionListResponse.model_validate(c) for c in connections],
        total=total,
        page=page,
        per_page=per_page
    )


@router.post("/connections", response_model=IPsecConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_ipsec_connection(
    data: IPsecConnectionCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new IPsec connection (admin only).

    The connection will be saved to the database but not applied until
    you call the /apply endpoint.
    """
    service = IPsecService(db)

    connection, error = await service.create_connection(data, admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    # Push the config to StrongSwan right away (mirrors the Firewall auto-apply).
    # Don't fail the request if the agent is down — the connection is already saved.
    applied, apply_err = await service.apply_config()
    if not applied:
        logger.warning(f"Connection created but config not applied: {apply_err}")

    # Refresh NAT gateway so this tunnel's remote subnet is auto-excluded from masquerade.
    from app.api.v1.routes.firewall import apply_gateway_via_agent
    await apply_gateway_via_agent()

    return connection


@router.get("/connections/{connection_id}", response_model=IPsecConnectionResponse)
async def get_ipsec_connection(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get IPsec connection details (admin only)"""
    service = IPsecService(db)

    connection = await service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    return connection


@router.put("/connections/{connection_id}", response_model=IPsecConnectionResponse)
async def update_ipsec_connection(
    connection_id: UUID,
    data: IPsecConnectionUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update IPsec connection (admin only).

    After updating, call /apply to write the new configuration.
    """
    service = IPsecService(db)

    connection = await service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    updated_connection, error = await service.update_connection(connection, data, admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    # Snapshot control values NOW: async SQLAlchemy expires attributes after the
    # commit inside update_connection, so reading them after the awaits below would
    # trigger a lazy refresh outside the greenlet -> DetachedInstanceError.
    conn_name = updated_connection.name
    tunnel_was_active = bool(
        updated_connection.is_enabled
        and updated_connection.status == IPsecStatus.ACTIVE
    )

    # Regenerate and apply so the running swanctl config reflects the change without a
    # manual Apply click. Don't fail the request if the agent is down — it's saved.
    applied, apply_err = await service.apply_config()
    if not applied:
        logger.warning(f"Connection updated but config not applied: {apply_err}")

    # Refresh NAT gateway so any changed remote subnet stays auto-excluded from masquerade.
    from app.api.v1.routes.firewall import apply_gateway_via_agent
    await apply_gateway_via_agent()

    # If the tunnel is live, restart it to renegotiate with the new proposal
    # (e.g. a changed Phase 2 / esp_cipher). A reload alone won't renegotiate.
    if tunnel_was_active:
        await service.restart_connection(conn_name)

    # Re-fetch fresh: the awaits above (apply/gateway/restart) expire the ORM
    # attributes, so serializing `updated_connection` directly would trigger a lazy
    # refresh on a detached instance -> DetachedInstanceError -> 500 (even though the
    # save + apply already succeeded). Returning a freshly-loaded, session-bound copy
    # avoids the misleading error that makes the panel look like the edit failed.
    fresh = await service.get_connection_by_id(connection_id)
    return fresh or updated_connection


@router.delete("/connections/{connection_id}", response_model=MessageResponse)
async def delete_ipsec_connection(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete IPsec connection (admin only).

    If the connection is active, it will be stopped first.
    After deleting, call /apply to update the configuration.
    """
    service = IPsecService(db)

    connection = await service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    success, error = await service.delete_connection(connection, admin)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    # Regenerate and apply so the removed connection is unloaded from swanctl
    # (swanctl --load-all reconciles: it unloads connections no longer in the config).
    applied, apply_err = await service.apply_config()
    if not applied:
        logger.warning(f"Connection deleted but config not reapplied: {apply_err}")

    # Refresh NAT gateway so the removed tunnel's subnet is no longer excluded.
    from app.api.v1.routes.firewall import apply_gateway_via_agent
    await apply_gateway_via_agent()

    return MessageResponse(message="IPsec connection deleted")


# ==================== Connection Control ====================

@router.post("/connections/{connection_id}/start")
async def start_ipsec_connection(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start/initiate an IPsec tunnel (admin only).

    Runs 'ipsec up <connection_name>' to establish the tunnel.
    """
    service = IPsecService(db)

    connection = await service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    success, output = await service.start_connection(connection.name)

    if not success:
        # Determine error type for better feedback
        error_info = {
            "success": False,
            "connection": connection.name,
            "error": output,
            "error_type": "unknown"
        }

        output_lower = output.lower()
        if "not found" in output_lower or "not installed" in output_lower:
            error_info["error_type"] = "strongswan_not_installed"
            error_info["suggestion"] = "StrongSwan is not installed or not accessible. Install with: apt install strongswan"
        elif "no config" in output_lower or "unknown connection" in output_lower:
            error_info["error_type"] = "config_not_applied"
            error_info["suggestion"] = "Configuration not applied. Click 'Apply Config' first."
        elif "authentication" in output_lower or "auth" in output_lower:
            error_info["error_type"] = "authentication_failed"
            error_info["suggestion"] = "Authentication failed. Check PSK matches on both sides."
        elif "timeout" in output_lower or "timed out" in output_lower:
            error_info["error_type"] = "connection_timeout"
            error_info["suggestion"] = "Connection timed out. Check remote peer is reachable and firewall allows UDP 500/4500."
        elif "peer not responding" in output_lower:
            error_info["error_type"] = "peer_unreachable"
            error_info["suggestion"] = "Remote peer not responding. Verify IP address and that peer's IPsec is running."

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_info
        )

    return {"success": True, "message": f"Connection '{connection.name}' started successfully"}


@router.post("/connections/{connection_id}/stop", response_model=MessageResponse)
async def stop_ipsec_connection(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Stop/terminate an IPsec tunnel (admin only).

    Runs 'ipsec down <connection_name>' to close the tunnel.
    """
    service = IPsecService(db)

    connection = await service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    success, output = await service.stop_connection(connection.name)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop connection: {output}"
        )

    return MessageResponse(message=f"Connection '{connection.name}' stopped")


@router.post("/connections/{connection_id}/restart", response_model=MessageResponse)
async def restart_ipsec_connection(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Restart an IPsec tunnel (admin only).

    Stops and then starts the tunnel.
    """
    service = IPsecService(db)

    connection = await service.get_connection_by_id(connection_id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    success, output = await service.restart_connection(connection.name)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart connection: {output}"
        )

    return MessageResponse(message=f"Connection '{connection.name}' restarted")


# ==================== HA / Failover controls ====================

@router.post("/connections/{connection_id}/switch-backup")
async def switch_to_backup(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Manually switch the tunnel to prefer the BACKUP endpoint (admin only). Reorders
    remote_addrs (backup first) and re-initiates — both paths stay available."""
    service = IPsecService(db)
    connection = await service.get_connection_by_id(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IPsec connection not found")
    ok, msg = await service.set_prefer_backup(connection.name, True)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@router.post("/connections/{connection_id}/rollback-primary")
async def rollback_to_primary(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Manually switch the tunnel back to prefer the PRIMARY endpoint (admin only)."""
    service = IPsecService(db)
    connection = await service.get_connection_by_id(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IPsec connection not found")
    ok, msg = await service.set_prefer_backup(connection.name, False)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@router.post("/connections/{connection_id}/test-failover")
async def test_failover(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Simulate a path failure to verify failover (admin only): blocks the active peer
    endpoint so DPD trips and the tunnel fails over to the backup, then auto-restores.
    Returns immediately — poll /status to watch it live."""
    service = IPsecService(db)
    connection = await service.get_connection_by_id(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IPsec connection not found")
    result = await service.test_failover(connection.name)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error", "test failed"))
    return result


# ==================== Global Status & Control ====================

@router.get("/status", response_model=IPsecGlobalStatus)
async def get_ipsec_status(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get global IPsec status (admin only).

    Returns StrongSwan status including all tunnel statuses.
    """
    service = IPsecService(db)

    status_data = await service.get_status()

    return IPsecGlobalStatus(**status_data)


@router.get("/status/{connection_name}")
async def get_connection_status(
    connection_name: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get status of a specific IPsec connection (admin only)"""
    service = IPsecService(db)

    # Verify connection exists
    connection = await service.get_connection_by_name(connection_name)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IPsec connection not found"
        )

    status_data = await service.get_status(connection_name)

    return status_data


@router.post("/reload", response_model=IPsecReloadResponse)
async def reload_ipsec_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Reload StrongSwan configuration (admin only).

    Runs 'ipsec reload' to reload the configuration without
    disrupting established tunnels.
    """
    service = IPsecService(db)

    success, output = await service.reload_all()

    return IPsecReloadResponse(
        success=success,
        message="Configuration reloaded" if success else "Failed to reload",
        output=output
    )


@router.post("/apply", response_model=IPsecReloadResponse)
async def apply_ipsec_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Apply IPsec configuration (admin only).

    Generates ipsec.conf and ipsec.secrets from database
    and reloads StrongSwan.
    """
    service = IPsecService(db)

    success, error = await service.apply_config()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error or "Failed to apply configuration"
        )

    return IPsecReloadResponse(
        success=True,
        message="Configuration applied successfully"
    )


@router.post("/restart", response_model=IPsecReloadResponse)
async def restart_strongswan(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Restart StrongSwan service (admin only).

    This will disconnect all active tunnels temporarily.
    """
    service = IPsecService(db)

    success, output = await service.restart_strongswan()

    return IPsecReloadResponse(
        success=success,
        message="StrongSwan restarted" if success else "Failed to restart",
        output=output
    )


# ==================== Peer-device export (FortiGate / generic) ====================

_DH_TO_GRP = {"modp1024": "2", "modp1536": "5", "modp2048": "14",
              "modp3072": "15", "modp4096": "16"}


def _split_cipher(cipher: str):
    """'aes256-sha256-modp2048' -> ('aes256-sha256', '14') for FortiGate (proposal +
    separate dhgrp). Falls back to sane defaults."""
    parts = [p for p in (cipher or "").split("-") if p]
    dhgrp = "14"
    prop = []
    for p in parts:
        if p in _DH_TO_GRP:
            dhgrp = _DH_TO_GRP[p]
        else:
            prop.append(p)
    return ("-".join(prop) or "aes256-sha256"), dhgrp


def _export_generic(c) -> str:
    backup = (c.right_ip_backup or "").strip() or "—"
    enc_ike = c.ike_cipher or "aes256-sha256-modp2048"
    enc_esp = c.esp_cipher or "aes256-sha256"
    return (
        "# ============================================================================\n"
        f'#  IPsec Site-to-Site — parâmetros da conexão "{c.name}"\n'
        "#  Gerado pelo EdgeGate. Use estes dados para fechar o túnel em\n"
        "#  QUALQUER equipamento (pfSense, Endian, MikroTik, Cisco, etc).\n"
        "# ============================================================================\n\n"
        "──[ NOSSO LADO — EdgeGate ]─────────────────────────────────────────\n"
        f"  Gateway remoto (aponte o peer para cá) : {c.left_id}\n"
        f"  IKE identifier (nosso ID)              : {c.left_id}\n"
        f"  Rede(s) local(is) que anunciamos       : {c.left_subnet}\n\n"
        "──[ LADO DO CLIENTE — equipamento remoto ]──────────────────────────\n"
        f"  IP público primário                    : {c.right_ip}\n"
        f"  IP público backup (failover, opcional) : {backup}\n"
        f"  Rede(s) atrás do cliente               : {c.right_subnet}\n\n"
        "──[ FASE 1 — IKE ]──────────────────────────────────────────────────\n"
        f"  Versão                                 : {c.ike_version.value.upper()}\n"
        f"  Autenticação                           : PSK (pre-shared key)\n"
        f"  Pre-shared key                         : {c.psk or '—'}\n"
        f"  Proposta (enc-hash-dh)                 : {enc_ike}\n"
        f"  Lifetime                               : {c.ike_lifetime}\n\n"
        "──[ FASE 2 — ESP ]──────────────────────────────────────────────────\n"
        f"  Proposta (enc-hash[-pfs])              : {enc_esp}\n"
        f"  Lifetime                               : {c.key_lifetime}\n\n"
        "──[ DPD / detecção de queda ]───────────────────────────────────────\n"
        f"  Ação                                   : {c.dpd_action.value}\n\n"
        "──[ Notas ]─────────────────────────────────────────────────────────\n"
        "  • Túnel roteado (route-based) recomendado.\n"
        f"  • Traffic selectors: {c.left_subnet}  ⇄  {c.right_subnet}\n"
        "  • NÃO aplicar NAT no tráfego do túnel (preserve os IPs reais).\n"
    )


def _fg_base(base: str, conn_name: str) -> str:
    """Sanitize the FortiGate name base: letters/digits/hyphen only, <=12 chars (so
    `<base>-01` fits the 15-char phase1-interface limit)."""
    b = "".join(ch for ch in (base or "") if ch.isalnum() or ch == "-").strip("-")[:12]
    if not b:
        b = "".join(ch for ch in conn_name if ch.isalnum() or ch == "-").strip("-")[:12]
    return b or "EGtun"


def _export_fortigate(c, fortios, wan_pri, wan_bak, lan_if, sla_src, lid_pri, lid_bak,
                      base, client_lan) -> str:
    prop_ike, dhgrp = _split_cipher(c.ike_cipher)
    prop_esp, esp_grp = _split_cipher(c.esp_cipher)
    # Phase-2 PFS must mirror EdgeGate's swanctl esp_proposals, NOT the IKE cipher.
    # Emitting the IKE dhgrp on phase2 told the FortiGate to enable PFS (dhgrp 14)
    # while our swanctl ran no-PFS ESP (esp_cipher without a modp group) -> the peer's
    # CREATE_CHILD_SA (with KE) was rejected NO_PROPOSAL_CHOSEN and the tunnel died on
    # the first CHILD_SA rekey. Only enable PFS here when the ESP cipher carries a DH
    # group; otherwise disable it so both ends agree (FortiGate phase2 defaults to PFS).
    esp_has_pfs = any(p in _DH_TO_GRP for p in (c.esp_cipher or "").split("-"))
    p2pfs = f"set pfs enable\n        set dhgrp {esp_grp}" if esp_has_pfs else "set pfs disable"
    # FortiGate object names (constraints: phase1 <= 15 chars, SLA must have NO hyphen)
    b = _fg_base(base, c.name)
    n1, n2 = f"{b}-01", f"{b}-02"
    sla = "".join(ch for ch in b if ch.isalnum()) or "EGSLA"   # health-check: no hyphen
    zone, net_addr, cli_addr = f"{b}-zone", f"{b}-net", f"{b}-cli"
    rule, pol_out, pol_in = f"{b}-rule", f"{b}-pol-out", f"{b}-pol-in"

    lsub = c.left_subnet.split(",")[0].strip()
    rsub = c.right_subnet.split(",")[0].strip()
    net = ipaddress.ip_network(lsub, strict=False)
    lnet, lmask = str(net.network_address), str(net.netmask)
    rnet_o = ipaddress.ip_network(rsub, strict=False)
    rnet, rmask = str(rnet_o.network_address), str(rnet_o.netmask)

    # Policy source = the client's LAN. Default to the client's protected subnet (an
    # address object, tighter than "all"); "all" keeps the permissive behaviour.
    cl = (client_lan or "").strip() or rsub
    if cl.lower() == "all":
        cli_src, cli_block = "all", ""
    else:
        cli_o = ipaddress.ip_network(cl, strict=False)
        cli_src = cli_addr
        cli_block = (f'    edit "{cli_addr}"\n'
                     f'        set subnet {cli_o.network_address} {cli_o.netmask}\n'
                     f'    next\n')
    psk = c.psk or "<PSK>"

    # Single link, but built INSIDE an SD-WAN zone with ONE member. This is the key to a
    # clean 1-link -> 2-link upgrade: the interface {n1} is already an SD-WAN member and
    # the route/policies already reference the zone (not the interface), so adding a backup
    # later is purely additive (drop in {n2} as member 202 and bump the health-check /
    # service to `members 201 202`) — no "interface in use" conflict, no UNDO needed. A
    # single-member SD-WAN is valid; the SLA source is required just like in failover.
    if not (c.right_ip_backup or "").strip():
        return f"""# ============================================================================
#  EdgeGate → FortiGate  |  IPsec single-link (SD-WAN, 1 membro)  |  conexão: {c.name}  (base: {b})
#  Alvo: FortiOS {fortios}   |   ⚠ REVISE antes de colar. Aditivo. Pronto p/ failover.
#  Já nasce em zona SD-WAN: adicionar um 2º link depois é só reinjetar a versão failover.
# ============================================================================

config firewall address
    edit "{net_addr}"
        set allow-routing enable
        set subnet {lnet} {lmask}
    next
{cli_block}end

config vpn ipsec phase1-interface
    edit "{n1}"
        set interface "{wan_pri}"
        set ike-version 2
        set keylife 28800
        set peertype any
        set net-device disable
        set proposal {prop_ike}
        set dhgrp {dhgrp}
        set localid "{lid_pri}"
        set remote-gw {c.left_id}
        set psksecret {psk}
    next
end
config vpn ipsec phase2-interface
    edit "{n1}"
        set phase1name "{n1}"
        set proposal {prop_esp}
        {p2pfs}
        set auto-negotiate enable
        set keylifeseconds 3600
        set src-subnet {rnet} {rmask}
        set dst-subnet {lnet} {lmask}
    next
end

config system sdwan
    set status enable
    config zone
        edit "{zone}"
        next
    end
    config members
        edit 201
            set interface "{n1}"
            set zone "{zone}"
            set source {sla_src}
        next
    end
    config health-check
        edit "{sla}"
            set server "{c.left_ip}"
            set source {sla_src}
            set members 201
            config sla
                edit 1
                    set latency-threshold 150
                next
            end
        next
    end
    config service
        edit 201
            set name "{rule}"
            set mode sla
            set dst "{net_addr}"
            set src "{cli_src}"
            config sla
                edit "{sla}"
                    set id 1
                next
            end
            set priority-members 201
            set priority-zone "{zone}"
        next
    end
end

config router static
    edit 0
        set dst {lnet} {lmask}
        set distance 1
        set sdwan-zone "{zone}"
    next
    edit 0
        set dst {lnet} {lmask}
        set distance 254
        set blackhole enable
    next
end

config firewall policy
    edit 0
        set name "{pol_out}"
        set srcintf "{lan_if}"
        set dstintf "{zone}"
        set action accept
        set srcaddr "{cli_src}"
        set dstaddr "{net_addr}"
        set schedule "always"
        set service "ALL"
    next
    edit 0
        set name "{pol_in}"
        set srcintf "{zone}"
        set dstintf "{lan_if}"
        set action accept
        set srcaddr "{net_addr}"
        set dstaddr "{cli_src}"
        set schedule "always"
        set service "ALL"
    next
end

# ── IMPORTANTE (depois de colar) ────────────────────────────────────────────
# 1) Rode  diagnose sys session clear  — sessões em cache seguram o caminho antigo
#    (rota/NAT) e o tráfego "vai mas não volta". Filtre p/ nossa rede se preferir:
#      diagnose sys session filter dst {lnet}
#      diagnose sys session clear
# 2) Se você usa Central SNAT, o `nat disable` das policies é IGNORADO — adicione
#    uma exceção no-NAT p/ esta VPN (orig={cli_src if cli_src != 'all' else '<rede-cliente>'},
#    dst={net_addr}, nat disable) no topo do central-snat-map, senão o transit sai
#    NATeado pela WAN e a volta quebra.
# 3) O SLA precisa ter `source` dentro da rede protegida do cliente (já setado acima).
# 4) UPGRADE p/ failover: preencha o IP de backup na conexão e reinjete o download —
#    ele adiciona {b}-02 como membro 202 e sobe o health-check/service p/ `201 202`.
#    Nada a desfazer aqui: a {n1} já é membro de SD-WAN, rota e policies já são por zona.
# 5) ORDEM — policies e a SD-WAN rule entram no FIM da lista (edit 0 = aditivo). Para
#    colocá-las no topo:
#      config firewall policy
#          move <id-{pol_out}> before <id-da-1a-policy-do-topo>
#          move <id-{pol_in}>  before <id-da-1a-policy-do-topo>
#      end
#      config system sdwan
#          config service
#              move 201 before <id-da-1a-service-rule>   # nossa rule "{rule}" = 201
#          end
#      end
#    (No GUI: arraste as policies em Firewall Policy e a rule em Network → SD-WAN → Rules.)
#
# ── UNDO ─ cole para remover tudo acima ─────────────────────────────────────
# firewall policy: delete {pol_out} / {pol_in}
# router static: delete as rotas (dst {lnet}/{lmask})
# system sdwan: service(del 201) -> health-check(del {sla}) -> members(del 201) -> zone(del {zone})
# vpn ipsec phase2/phase1-interface: delete {n1}
# firewall address: delete {net_addr}{(' / ' + cli_addr) if cli_src != 'all' else ''}
"""

    return f"""# ============================================================================
#  EdgeGate → FortiGate  |  IPsec HA/Failover  |  conexão: {c.name}  (base: {b})
#  Alvo: FortiOS {fortios}   |   ⚠ REVISE antes de colar. Aditivo. UNDO no rodapé.
# ============================================================================

config firewall address
    edit "{net_addr}"
        set allow-routing enable
        set subnet {lnet} {lmask}
    next
{cli_block}end

config vpn ipsec phase1-interface
    edit "{n1}"
        set interface "{wan_pri}"
        set ike-version 2
        set keylife 28800
        set peertype any
        set net-device disable
        set proposal {prop_ike}
        set dhgrp {dhgrp}
        set localid "{lid_pri}"
        set remote-gw {c.left_id}
        set psksecret {psk}
    next
    edit "{n2}"
        set interface "{wan_bak}"
        set ike-version 2
        set keylife 28800
        set peertype any
        set net-device disable
        set proposal {prop_ike}
        set dhgrp {dhgrp}
        set localid "{lid_bak}"
        set remote-gw {c.left_id}
        set psksecret {psk}
    next
end
config vpn ipsec phase2-interface
    edit "{n1}"
        set phase1name "{n1}"
        set proposal {prop_esp}
        {p2pfs}
        set auto-negotiate enable
        set keylifeseconds 3600
        set src-subnet {rnet} {rmask}
        set dst-subnet {lnet} {lmask}
    next
    edit "{n2}"
        set phase1name "{n2}"
        set proposal {prop_esp}
        {p2pfs}
        set auto-negotiate enable
        set keylifeseconds 3600
        set src-subnet {rnet} {rmask}
        set dst-subnet {lnet} {lmask}
    next
end

config system sdwan
    set status enable
    config zone
        edit "{zone}"
        next
    end
    config members
        edit 201
            set interface "{n1}"
            set zone "{zone}"
            set source {sla_src}
        next
        edit 202
            set interface "{n2}"
            set zone "{zone}"
            set source {sla_src}
        next
    end
    config health-check
        edit "{sla}"
            set server "{c.left_ip}"
            set source {sla_src}
            set members 201 202
            config sla
                edit 1
                    set latency-threshold 150
                next
            end
        next
    end
    config service
        edit 201
            set name "{rule}"
            set mode sla
            set dst "{net_addr}"
            set src "{cli_src}"
            config sla
                edit "{sla}"
                    set id 1
                next
            end
            set priority-members 201 202
            set priority-zone "{zone}"
        next
    end
end

config router static
    edit 0
        set dst {lnet} {lmask}
        set distance 1
        set sdwan-zone "{zone}"
    next
    edit 0
        set dst {lnet} {lmask}
        set distance 254
        set blackhole enable
    next
end

config firewall policy
    edit 0
        set name "{pol_out}"
        set srcintf "{lan_if}"
        set dstintf "{zone}"
        set action accept
        set srcaddr "{cli_src}"
        set dstaddr "{net_addr}"
        set schedule "always"
        set service "ALL"
    next
    edit 0
        set name "{pol_in}"
        set srcintf "{zone}"
        set dstintf "{lan_if}"
        set action accept
        set srcaddr "{net_addr}"
        set dstaddr "{cli_src}"
        set schedule "always"
        set service "ALL"
    next
end

# ── IMPORTANTE (depois de colar) ────────────────────────────────────────────
# 1) Rode  diagnose sys session clear  — sessões em cache seguram o caminho antigo
#    (rota/NAT) e o tráfego "vai mas não volta". Filtre p/ nossa rede se preferir:
#      diagnose sys session filter dst {lnet}
#      diagnose sys session clear
# 2) Se você usa Central SNAT, o `nat disable` das policies é IGNORADO — adicione
#    uma exceção no-NAT p/ esta VPN (orig={cli_src if cli_src != 'all' else '<rede-cliente>'},
#    dst={net_addr}, nat disable) no topo do central-snat-map, senão o transit sai
#    NATeado pela WAN e a volta quebra.
# 3) O SLA precisa ter `source` dentro da rede protegida do cliente (já setado acima).
# 4) ORDEM — as policies e a SD-WAN rule entram no FIM da lista (edit 0 = aditivo,
#    não colide). Para colocá-las no topo (a rule precisa vencer uma SD-WAN default,
#    e as policies uma policy mais ampla que as sombreie):
#      config firewall policy
#          move <id-{pol_out}> before <id-da-1a-policy-do-topo>
#          move <id-{pol_in}>  before <id-da-1a-policy-do-topo>
#      end
#      config system sdwan
#          config service
#              move 201 before <id-da-1a-service-rule>   # nossa rule "{rule}" = 201
#          end
#      end
#    (No GUI: arraste as policies em Firewall Policy e a rule em Network → SD-WAN → Rules.)
#
# ── UNDO ─ cole para remover tudo acima ─────────────────────────────────────
# firewall policy: delete {pol_out} / {pol_in}
# router static: delete as rotas (dst {lnet}/{lmask})
# system sdwan: service(del 201) -> health-check(del {sla}) -> members(del 201 202) -> zone(del {zone})
# vpn ipsec phase2/phase1-interface: delete {n1} / {n2}
# firewall address: delete {net_addr}{(' / ' + cli_addr) if cli_src != 'all' else ''}
"""


@router.get("/connections/{connection_id}/export", response_class=PlainTextResponse)
async def export_connection_config(
    connection_id: UUID,
    target: str = Query("fortigate", pattern=r"^(fortigate|generic)$"),
    fortios: str = "7.4",
    wan_pri: str = "<WAN_PRI>",
    wan_bak: str = "<WAN_BAK>",
    lan_if: str = "<LAN_IF>",
    sla_src: str = "<SLA_SRC>",
    localid_pri: str = "",
    localid_bak: str = "",
    base: str = "",
    client_lan: str = "",
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Render this connection's config for the peer device. target=fortigate -> a
    paste-into-CLI script (SD-WAN failover, with the REAL PSK); target=generic -> a
    device-agnostic parameter sheet. FortiGate-specific bits come from the query;
    `base` names the FortiGate objects (<=12 chars) and `client_lan` scopes the policy
    source (a subnet -> an address object, or 'all')."""
    # Space-proof the free-text fields: a stray leading/trailing space (e.g. "VLAN 10 "
    # in an interface) yields an invalid `set interface "VLAN 10 "` that FortiGate rejects.
    # Trim only the ends — internal spaces are preserved.
    wan_pri, wan_bak, lan_if = wan_pri.strip(), wan_bak.strip(), lan_if.strip()
    sla_src, base = sla_src.strip(), base.strip()
    localid_pri, localid_bak, client_lan = localid_pri.strip(), localid_bak.strip(), client_lan.strip()
    service = IPsecService(db)
    conn = await service.get_connection_by_id(connection_id)
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IPsec connection not found")
    if target == "generic":
        return _export_generic(conn)
    # Local IDs: on a FAILOVER connection the two phase1 tunnels MUST present distinct IKE
    # identities, else each tunnel's INITIAL_CONTACT destroys the other on our responder and
    # the tunnel flaps (~every DPD interval). failover_peer_ids() derives a stable, distinct
    # id per path (`<right_id>-01`/`-02`) — the single source of truth shared with
    # to_swanctl_secret(), which keys the same ids so both paths authenticate. Single-link
    # connections have no war, so they keep the plain peer id. Explicit query overrides win.
    fo = conn.failover_peer_ids()
    if fo:
        default_pri, default_bak = fo
    else:
        default_pri = conn.right_id or conn.right_ip
        default_bak = conn.right_id or (conn.right_ip_backup or "")
    return _export_fortigate(
        conn, fortios, wan_pri, wan_bak, lan_if, sla_src,
        (localid_pri or default_pri),
        (localid_bak or default_bak),
        base, client_lan,
    )


# ==================== Config Preview ====================

@router.get("/connections/{connection_id}/config", response_class=PlainTextResponse)
async def get_connection_config(
    connection_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """The swanctl config this single connection generates (PSK masked). Read-only —
    lets an admin inspect exactly what gets written for this tunnel, per-connection."""
    service = IPsecService(db)
    conn = await service.get_connection_by_id(connection_id)
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IPsec connection not found")
    conn_block = conn.to_swanctl()
    secret_block = conn.to_swanctl_secret()
    if conn.psk:
        secret_block = secret_block.replace(f'"{conn.psk}"', '"••••••••••"')
    return (
        f"connections {{\n{conn_block}\n}}\n\n"
        f"secrets {{\n{secret_block}\n}}\n"
    )


@router.get("/config/preview", response_model=IPsecConfigPreview)
async def preview_ipsec_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Preview generated IPsec configuration (admin only).

    Shows what will be written to ipsec.conf and ipsec.secrets
    without applying.
    """
    service = IPsecService(db)

    preview = await service.get_preview()

    return IPsecConfigPreview(**preview)


@router.get("/config/ipsec.conf", response_class=PlainTextResponse)
async def get_ipsec_conf(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get generated ipsec.conf content (admin only)"""
    service = IPsecService(db)

    config = await service.generate_ipsec_conf()

    return PlainTextResponse(content=config)


@router.get("/config/ipsec.secrets", response_class=PlainTextResponse)
async def get_ipsec_secrets(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get generated ipsec.secrets content (admin only).

    WARNING: Contains sensitive PSK values.
    """
    service = IPsecService(db)

    secrets = await service.generate_ipsec_secrets()

    return PlainTextResponse(content=secrets)


# ==================== Utility Endpoints ====================

@router.get("/version")
async def get_strongswan_version(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get StrongSwan version (admin only)"""
    service = IPsecService(db)

    version = await service.get_strongswan_version()
    installed = await service.check_strongswan_installed()

    return {
        "installed": installed,
        "version": version
    }


@router.get("/statusall")
async def get_detailed_status(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed IPsec status (admin only).

    Returns the raw output of 'ipsec statusall' command,
    similar to what you see on Endian Firewall or other IPsec managers.
    """
    service = IPsecService(db)
    return await service.get_detailed_status()


@router.get("/logs")
async def get_ipsec_logs(
    lines: int = Query(100, ge=10, le=1000),
    connection: Optional[str] = Query(None, description="Filter logs by connection name"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent IPsec/StrongSwan logs (admin only).

    Returns the last N lines of StrongSwan logs.
    Optionally filter by connection name.
    """
    service = IPsecService(db)
    return await service.get_logs(lines, connection)


@router.post("/sync-status", response_model=MessageResponse)
async def sync_connection_statuses(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Sync connection statuses from StrongSwan (admin only).

    Updates the database status for all connections based on
    actual StrongSwan status.
    """
    service = IPsecService(db)

    await service.update_connection_statuses()

    return MessageResponse(message="Connection statuses synchronized")


@router.get("/server-info")
async def get_server_network_info(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get server network information for IPsec configuration (admin only).

    Returns:
    - private_ip: Server's private/internal IP address
    - public_ip: Server's public IP address (from AWS metadata or external service)
    - local_subnet: Local network subnet in CIDR notation
    - interface: Primary network interface name
    """
    service = IPsecService(db)

    return service.get_server_network_info()
