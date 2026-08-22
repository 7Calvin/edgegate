"""
IPsec Service - Manages StrongSwan IPsec Site-to-Site VPN connections
"""
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime
from uuid import UUID
import subprocess
import logging
import re
import os
import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.ipsec import IPsecConnection, IPsecStatus
from app.models.user import User
from app.schemas.ipsec import IPsecConnectionCreate, IPsecConnectionUpdate

logger = logging.getLogger(__name__)

# IPsec Agent configuration
IPSEC_AGENT_URL = os.environ.get("IPSEC_AGENT_URL", "http://127.0.0.1:8101")
IPSEC_AGENT_TOKEN = os.environ.get("IPSEC_AGENT_TOKEN", "changeme-ipsec-token")


class IPsecService:
    """StrongSwan IPsec connection management"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ipsec_conf_path = "/etc/ipsec.conf"
        self.ipsec_secrets_path = "/etc/ipsec.secrets"
        self.agent_url = IPSEC_AGENT_URL
        self.agent_token = IPSEC_AGENT_TOKEN

    # ==================== CRUD Operations ====================

    async def get_connection_by_id(self, connection_id: UUID) -> Optional[IPsecConnection]:
        """Get IPsec connection by ID"""
        result = await self.db.execute(
            select(IPsecConnection).where(IPsecConnection.id == connection_id)
        )
        return result.scalar_one_or_none()

    async def get_connection_by_name(self, name: str) -> Optional[IPsecConnection]:
        """Get IPsec connection by name"""
        result = await self.db.execute(
            select(IPsecConnection).where(IPsecConnection.name == name)
        )
        return result.scalar_one_or_none()

    async def list_connections(
        self,
        is_enabled: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[IPsecConnection], int]:
        """List IPsec connections with filtering and pagination"""
        query = select(IPsecConnection)

        if is_enabled is not None:
            query = query.where(IPsecConnection.is_enabled == is_enabled)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.execute(count_query)
        total_count = total.scalar()

        # Apply ordering and pagination
        query = query.order_by(
            IPsecConnection.name
        ).offset(skip).limit(limit)

        result = await self.db.execute(query)
        connections = result.scalars().all()

        return list(connections), total_count

    async def create_connection(
        self,
        data: IPsecConnectionCreate,
        created_by: User
    ) -> Tuple[Optional[IPsecConnection], Optional[str]]:
        """Create a new IPsec connection"""
        # Check for duplicate name
        existing = await self.get_connection_by_name(data.name)
        if existing:
            return None, f"Connection with name '{data.name}' already exists"

        # Validate PSK is provided for PSK auth
        if data.auth_method == "psk" and not data.psk:
            return None, "PSK (Pre-Shared Key) is required for PSK authentication"

        connection = IPsecConnection(
            name=data.name,
            description=data.description,
            left_ip=data.left_ip,
            left_subnet=data.left_subnet,
            left_id=data.left_id,
            right_ip=data.right_ip,
            right_ip_backup=data.right_ip_backup,
            right_subnet=data.right_subnet,
            right_id=data.right_id or data.right_ip,  # default the peer ID to its IP
            auth_method=data.auth_method,
            psk=data.psk,
            ike_version=data.ike_version,
            ike_cipher=data.ike_cipher,
            ike_lifetime=data.ike_lifetime,
            esp_cipher=data.esp_cipher,
            key_lifetime=data.key_lifetime,
            auto_start=data.auto_start,
            dpd_action=data.dpd_action,
            is_enabled=data.is_enabled,
            status=IPsecStatus.INACTIVE,
            created_by_id=created_by.id,
        )

        self.db.add(connection)
        await self.db.commit()
        await self.db.refresh(connection)

        logger.info(f"IPsec connection created: {connection.name} by {created_by.username}")
        return connection, None

    async def update_connection(
        self,
        connection: IPsecConnection,
        data: IPsecConnectionUpdate,
        updated_by: User
    ) -> Tuple[IPsecConnection, Optional[str]]:
        """Update an IPsec connection"""
        update_data = data.model_dump(exclude_unset=True)

        # Check for name conflict if name is being changed
        if "name" in update_data and update_data["name"] != connection.name:
            existing = await self.get_connection_by_name(update_data["name"])
            if existing:
                return connection, f"Connection with name '{update_data['name']}' already exists"

        for field, value in update_data.items():
            setattr(connection, field, value)

        await self.db.commit()
        await self.db.refresh(connection)

        logger.info(f"IPsec connection updated: {connection.name} by {updated_by.username}")
        return connection, None

    async def delete_connection(
        self,
        connection: IPsecConnection,
        deleted_by: User
    ) -> Tuple[bool, Optional[str]]:
        """Delete an IPsec connection"""
        # Stop the connection first if active
        if connection.status == IPsecStatus.ACTIVE:
            await self.stop_connection(connection.name)

        connection_name = connection.name
        await self.db.delete(connection)
        await self.db.commit()

        logger.info(f"IPsec connection deleted: {connection_name} by {deleted_by.username}")
        return True, None

    # ==================== Config Generation ====================

    async def generate_ipsec_conf(self) -> str:
        """Generate complete ipsec.conf file content"""
        connections, _ = await self.list_connections(is_enabled=True)

        lines = [
            "# ipsec.conf - StrongSwan IPsec configuration file",
            "# Auto-generated by EdgeGate",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            "",
            "# Basic configuration",
            "config setup",
            "    # strictcrlpolicy=yes",
            "    # uniqueids = no",
            "",
        ]

        # Add connection blocks
        for conn in connections:
            lines.append(f"# Connection: {conn.name}")
            if conn.description:
                lines.append(f"# {conn.description}")
            lines.append(conn.to_ipsec_conf())
            lines.append("#" * 80)
            lines.append("")

        return "\n".join(lines)

    async def generate_ipsec_secrets(self) -> str:
        """Generate complete ipsec.secrets file content"""
        connections, _ = await self.list_connections(is_enabled=True)

        lines = [
            "# ipsec.secrets - StrongSwan IPsec secrets file",
            "# Auto-generated by EdgeGate",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            "",
            "# This file holds shared secrets or RSA private keys for authentication.",
            "# Format: IP_LOCAL IP_REMOTE : PSK \"key\"",
            "",
        ]

        for conn in connections:
            secret_line = conn.to_ipsec_secret()
            if secret_line:
                lines.append(f"# {conn.name}")
                lines.append(secret_line)
                lines.append("")

        return "\n".join(lines)

    async def generate_swanctl_config(self) -> str:
        """Generate the complete swanctl.conf (connections {} + secrets {}) for all
        enabled connections. This is the swanctl/vici replacement for ipsec.conf."""
        connections, _ = await self.list_connections(is_enabled=True)

        conn_blocks = [c.to_swanctl() for c in connections]
        secret_blocks = [s for s in (c.to_swanctl_secret() for c in connections) if s]

        lines = [
            "# swanctl.conf - Auto-generated by EdgeGate",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            "",
            "connections {",
            "\n\n".join(conn_blocks),
            "}",
            "",
            "secrets {",
            "\n\n".join(secret_blocks),
            "}",
            "",
        ]
        return "\n".join(lines)

    async def apply_config(self) -> Tuple[bool, Optional[str]]:
        """Write swanctl.conf and (re)load it via the ipsec-agent."""
        try:
            swanctl_conf = await self.generate_swanctl_config()

            # Write config via agent (agent writes /etc/swanctl/conf.d/*.conf)
            success, error = await self._agent_write_config(swanctl_conf)
            if not success:
                return False, f"Failed to write config: {error}"

            # Reload swanctl (agent runs `swanctl --load-all`)
            success, output = await self._run_ipsec_command_async(["reload"])
            if not success:
                return False, f"Failed to reload swanctl: {output}"

            logger.info("IPsec (swanctl) configuration applied successfully")
            return True, None

        except Exception as e:
            logger.error(f"Failed to apply IPsec config: {e}")
            return False, str(e)

    async def _agent_write_config(self, swanctl_conf: str) -> Tuple[bool, Optional[str]]:
        """Write the swanctl config via the ipsec-agent API (agent writes it to
        /etc/swanctl/conf.d/ and loads it)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.agent_url}/config/write",
                    headers={"Authorization": f"Bearer {self.agent_token}"},
                    json={"swanctl_conf": swanctl_conf}
                )

                if response.status_code == 401:
                    return False, "Unauthorized - check IPSEC_AGENT_TOKEN"

                if response.status_code != 200:
                    return False, f"Agent returned status {response.status_code}"

                data = response.json()
                if data.get("swanctl_conf", {}).get("success") is False:
                    return False, f"swanctl.conf: {data['swanctl_conf'].get('error', 'unknown error')}"

                return True, None

        except httpx.ConnectError:
            return False, "Cannot connect to ipsec-agent - is it running on the host?"
        except httpx.TimeoutException:
            return False, "Timeout connecting to ipsec-agent"
        except Exception as e:
            return False, str(e)

    def _write_file(self, path: str, content: str) -> Tuple[bool, Optional[str]]:
        """Write content to file (local fallback)"""
        try:
            with open(path, 'w') as f:
                f.write(content)
            return True, None
        except Exception as e:
            return False, str(e)

    # ==================== StrongSwan Control ====================

    async def _run_ipsec_command_async(self, args: List[str]) -> Tuple[bool, str]:
        """Run ipsec command via ipsec-agent API and return (success, output)"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Map command args to agent endpoints
                if len(args) >= 1:
                    cmd = args[0]

                    if cmd == "version":
                        response = await client.get(
                            f"{self.agent_url}/version",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    elif cmd == "statusall":
                        response = await client.get(
                            f"{self.agent_url}/status",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    elif cmd == "status" and len(args) >= 2:
                        response = await client.get(
                            f"{self.agent_url}/status/{args[1]}",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    elif cmd == "up" and len(args) >= 2:
                        response = await client.post(
                            f"{self.agent_url}/up/{args[1]}",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    elif cmd == "down" and len(args) >= 2:
                        response = await client.post(
                            f"{self.agent_url}/down/{args[1]}",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    elif cmd == "reload":
                        response = await client.post(
                            f"{self.agent_url}/reload",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    elif cmd == "restart":
                        response = await client.post(
                            f"{self.agent_url}/restart",
                            headers={"Authorization": f"Bearer {self.agent_token}"}
                        )
                    else:
                        return False, f"Unknown ipsec command: {' '.join(args)}"

                    if response.status_code == 401:
                        return False, "Unauthorized - check IPSEC_AGENT_TOKEN"

                    data = response.json()
                    success = data.get("success", False)
                    output = data.get("output", data.get("stdout", ""))

                    if not success:
                        # Detect daemon not running (empty output with failure)
                        if not output and data.get("returncode") in (7, -1, 1):
                            output = "StrongSwan daemon (charon) is not running. Try restarting StrongSwan first."
                        logger.warning(f"ipsec command failed via agent: {' '.join(args)} - {output}")

                    return success, output

                return False, "No command specified"

        except httpx.ConnectError:
            return False, "Cannot connect to ipsec-agent - is it running on the host? Install with: cd docker/ipsec-agent && sudo ./install.sh"
        except httpx.TimeoutException:
            return False, "Timeout connecting to ipsec-agent"
        except Exception as e:
            logger.error(f"Error calling ipsec-agent: {e}")
            return False, str(e)

    def _run_ipsec_command(self, args: List[str]) -> Tuple[bool, str]:
        """Run ipsec command synchronously (fallback for sync contexts)"""
        try:
            cmd = ["ipsec"] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            output = result.stdout + result.stderr
            success = result.returncode == 0

            if not success:
                logger.warning(f"ipsec command failed: {' '.join(args)} - {output}")

            return success, output.strip()

        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except FileNotFoundError:
            return False, "ipsec command not found - StrongSwan may not be installed"
        except Exception as e:
            return False, str(e)

    async def start_connection(self, name: str) -> Tuple[bool, str]:
        """Start/initiate an IPsec connection"""
        connection = await self.get_connection_by_name(name)
        if not connection:
            return False, f"Connection '{name}' not found"

        if not connection.is_enabled:
            return False, f"Connection '{name}' is disabled"

        success, output = await self._run_ipsec_command_async(["up", name])

        if success:
            connection.status = IPsecStatus.ACTIVE
            connection.last_error = None
        else:
            connection.status = IPsecStatus.ERROR
            connection.last_error = output

        connection.last_status_check = datetime.utcnow()
        await self.db.commit()

        return success, output

    async def stop_connection(self, name: str) -> Tuple[bool, str]:
        """Stop/terminate an IPsec connection"""
        connection = await self.get_connection_by_name(name)
        if not connection:
            return False, f"Connection '{name}' not found"

        success, output = await self._run_ipsec_command_async(["down", name])

        connection.status = IPsecStatus.INACTIVE
        connection.last_status_check = datetime.utcnow()
        if not success:
            connection.last_error = output
        await self.db.commit()

        return success, output

    async def restart_connection(self, name: str) -> Tuple[bool, str]:
        """Restart an IPsec connection"""
        # Stop first
        await self.stop_connection(name)

        # Then start
        return await self.start_connection(name)

    # ==================== HA / Failover controls ====================

    async def _agent_post(self, path: str, timeout: float = 20.0) -> Tuple[bool, Any]:
        """POST to the ipsec-agent (no body)."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    f"{self.agent_url}{path}",
                    headers={"Authorization": f"Bearer {self.agent_token}"},
                )
                ct = r.headers.get("content-type", "")
                return r.status_code == 200, (r.json() if ct.startswith("application/json") else r.text)
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    async def _active_remote(self, name: str) -> Optional[str]:
        """The remote endpoint currently carrying OUTBOUND traffic. Reads the kernel XFRM
        policy via the agent — with two overlapping failover SAs the outbound policy (the
        last SA installed) is the only reliable signal; swanctl list-sas / prefer_backup
        can't tell which path actually carries traffic. Falls back to list-sas remote_host."""
        ok, data = await self._agent_post("/active-remote")
        if ok and isinstance(data, dict) and data.get("active"):
            return data["active"]
        st = await self.get_status(name)
        for c in st.get("connections", []):
            if c.get("name") == name:
                return c.get("remote_host")
        return None

    async def set_prefer_backup(self, name: str, prefer: bool) -> Tuple[bool, str]:
        """Manual failover switch: prefer the backup endpoint (True) or the primary
        (False). Reorders remote_addrs, reloads, and restarts the tunnel so it
        re-initiates on the chosen endpoint. Both paths stay available (no blocking)."""
        conn = await self.get_connection_by_name(name)
        if not conn:
            return False, f"Connection '{name}' not found"
        backup = (conn.right_ip_backup or "").strip()
        if not backup:
            return False, "No backup IP configured on this connection"
        primary = conn.right_ip
        target = backup if prefer else primary
        conn.prefer_backup = prefer
        await self.db.commit()

        # Reorder remote_addrs (matters when WE initiate).
        ok, err = await self.apply_config()
        if not ok:
            return False, f"Config apply failed: {err}"

        # The peer (e.g. a FortiGate with a conn per IP) usually initiates from the
        # PRIMARY and wins the race, so a reorder alone won't force the backup. Block
        # the primary path to force the tunnel onto the backup; unblock to return.
        if prefer:
            await self._agent_post(f"/block-peer/{primary}")
        else:
            await self._agent_post(f"/unblock-peer/{primary}")

        await self.restart_connection(name)  # re-initiate on the now-forced endpoint
        return True, f"Now preferring {'backup' if prefer else 'primary'} ({target})"

    async def test_failover(self, name: str) -> Dict[str, Any]:
        """Simulate a path failure: block the active remote endpoint on the host so DPD
        trips and the tunnel fails over to the other IP; the agent auto-unblocks after a
        delay. Returns immediately — poll /status to watch the failover live."""
        conn = await self.get_connection_by_name(name)
        if not conn:
            return {"success": False, "error": "Connection not found"}
        backup = (conn.right_ip_backup or "").strip()
        if not backup:
            return {"success": False, "error": "No backup IP set — nothing to fail over to"}
        primary = conn.right_ip
        # Block whichever endpoint actually carries outbound traffic (read from the XFRM
        # policy via the agent). With both failover SAs up the active path = last SA
        # installed, which neither prefer_backup nor list-sas reliably reflects — so ask
        # the kernel, else the test may block the idle path and nothing fails over.
        active = await self._active_remote(name) or primary
        other = backup if active == primary else primary
        ok, out = await self._agent_post(f"/test-failover-block/{active}")
        if not ok:
            return {"success": False, "error": f"Could not start test: {out}"}
        return {
            "success": True,
            "blocking": active,
            "expected_failover_to": other,
            "message": f"Blocked {active}; the tunnel should fail over to {other} within "
                       f"~30-60s (auto-restored after). Watch the status.",
        }

    async def reload_all(self) -> Tuple[bool, str]:
        """Reload StrongSwan configuration"""
        return await self._run_ipsec_command_async(["reload"])

    async def restart_strongswan(self) -> Tuple[bool, str]:
        """Restart StrongSwan service"""
        return await self._run_ipsec_command_async(["restart"])

    # ==================== Status Monitoring ====================

    async def get_status(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Get IPsec connection status from StrongSwan"""
        if name:
            success, output = await self._run_ipsec_command_async(["status", name])
        else:
            success, output = await self._run_ipsec_command_async(["statusall"])

        if not success:
            return {
                "strongswan_running": False,
                "total_connections": 0,
                "active_tunnels": 0,
                "error": output,
                "connections": []
            }

        # Parse output
        result = self._parse_status_output(output)
        await self._enrich_status(result, single_name=name)
        return result

    async def _enrich_status(self, result: Dict[str, Any], single_name: Optional[str] = None) -> None:
        """Reconcile the parsed SA list with the DB and the kernel XFRM policy so the status
        reflects reality:
          - each live connection's `remote_host`/`on_backup` = the endpoint actually carrying
            outbound traffic (read via the agent `/active-remote`) — not `prefer_backup`;
          - every ENABLED connection with NO live SA is added as a DOWN entry (otherwise a
            fully-down tunnel just vanishes — there's no SA to parse);
          - total_connections = enabled connections (what SHOULD be up), active_tunnels = UP.
        Without this, both-tunnels-down => 0 SAs => total=0 => the 'túnel fora do ar' alert
        never fires and the connection disappears from the panel."""
        try:
            entries = result.get("connections") or []
            result["connections"] = entries
            by_entry = {e.get("name"): e for e in entries}

            ok, data = await self._agent_post("/active-remote")
            active = set((data or {}).get("all") or []) if (ok and isinstance(data, dict)) else set()

            q = select(IPsecConnection).where(IPsecConnection.is_enabled.is_(True))
            if single_name:
                q = q.where(IPsecConnection.name == single_name)
            rows = (await self.db.execute(q)).scalars().all()

            for c in rows:
                entry = by_entry.get(c.name)
                if entry is not None:
                    backup = (c.right_ip_backup or "").strip()
                    if active:
                        if c.right_ip in active:
                            entry["remote_host"] = c.right_ip
                            entry["on_backup"] = False if backup else None
                        elif backup and backup in active:
                            entry["remote_host"] = backup
                            entry["on_backup"] = True  # backup ativo => primário indisponível
                else:
                    entries.append({
                        "name": c.name, "status": "DOWN", "ike_status": "DOWN",
                        "tunnel_status": "DOWN", "has_child_sa": False, "active_paths": 0,
                        "remote_host": None, "on_backup": None, "uptime": None,
                        "local_ts": c.left_subnet, "remote_ts": c.right_subnet,
                        "bytes_in": None, "bytes_out": None, "rekey_time": None,
                        "error_hint": None,
                    })

            enabled_names = {c.name for c in rows}
            result["total_connections"] = len(rows)
            result["active_tunnels"] = sum(
                1 for e in entries if e.get("tunnel_status") == "UP" and e.get("name") in enabled_names
            )
        except Exception as e:  # noqa: BLE001 — never break status on enrichment
            logger.debug("status enrichment skipped: %s", e)

    def _parse_status_output(self, output: str) -> Dict[str, Any]:
        """Parse `swanctl --list-sas` text output into the status structure.

        Example block:
            to-macro01: #1, ESTABLISHED, IKEv2, <spis>
              local  '107.20.115.56' @ 10.10.22.83[500]
              remote '189.112.40.121' @ 189.112.40.121[500]
              AES_CBC-256/...
              established 506s ago, rekeying in 27255s
              to-macro01-net: #1, reqid 1, INSTALLED, TUNNEL, ESP:...
                in  <spi>,  30120 bytes,   502 packets,     1s ago
                out <spi>,  30120 bytes,   502 packets,     1s ago
                local  10.10.0.0/16
                remote 192.168.128.0/23
        """
        result = {
            "strongswan_running": True,
            "total_connections": 0,
            "active_tunnels": 0,
            "connections": []
        }
        if not output or not output.strip():
            return result

        # IKE SA header sits at column 0: "<conn>: #<n>, <STATE>, IKEv<n>, ..."
        ike_hdr = re.compile(
            r'^(\S+):\s+#\d+,\s+(ESTABLISHED|CONNECTING|ESTABLISHING|REKEYED|DELETING)\b')

        # Group lines into per-IKE-SA blocks.
        blocks: List[Dict[str, Any]] = []
        cur: Optional[Dict[str, Any]] = None
        for ln in output.splitlines():
            m = ike_hdr.match(ln)
            if m:
                cur = {"name": m.group(1), "ike_state": m.group(2), "lines": [ln]}
                blocks.append(cur)
            elif cur is not None:
                cur["lines"].append(ln)

        # Collapse SA blocks by connection name. A FAILOVER connection keeps TWO SAs up
        # at once (primary + backup endpoints), and during a rekey there's briefly a 3rd
        # (duplicate) SA — so counting raw SA blocks made the dashboard read "2/3" for a
        # single connection. One entry per connection: UP if any path is up, with
        # `active_paths` = how many endpoints are currently carrying an established SA.
        by_conn: Dict[str, Dict[str, Any]] = {}
        rank = {"UP": 3, "IKE_ONLY": 2, "CONNECTING": 1, "DOWN": 0}
        for blk in blocks:
            conn_name = blk["name"]
            ike_state = blk["ike_state"]
            body = "\n".join(blk["lines"])

            child_installed = bool(re.search(r'reqid\s+\d+,\s+INSTALLED', body))
            has_child = child_installed or bool(re.search(r'reqid\s+\d+,\s+\w+', body))

            if ike_state == "ESTABLISHED" and child_installed:
                tunnel_status = "UP"
            elif ike_state == "ESTABLISHED":
                tunnel_status = "IKE_ONLY"
            elif ike_state in ("CONNECTING", "ESTABLISHING"):
                tunnel_status = "CONNECTING"
            else:
                tunnel_status = "DOWN"

            rh = re.search(r"^\s*remote\s+'[^']*'\s+@\s+(\S+?)\[", body, re.MULTILINE)
            remote_host = rh.group(1) if rh else None
            up = re.search(r'established\s+([^,\n]+)', body)
            bi = re.search(r'^\s*in\s+\S+,\s+(\d+)\s+bytes', body, re.MULTILINE)
            bo = re.search(r'^\s*out\s+\S+,\s+(\d+)\s+bytes', body, re.MULTILINE)
            lts = re.search(r'^\s*local\s+(\d[\d./]*(?:,\s*\d[\d./]*)*)\s*$', body, re.MULTILINE)
            rts = re.search(r'^\s*remote\s+(\d[\d./]*(?:,\s*\d[\d./]*)*)\s*$', body, re.MULTILINE)
            rk = re.search(r'rekeying in\s+(\S+)', body)

            entry = by_conn.get(conn_name)
            if entry is None:
                entry = {
                    "name": conn_name,
                    "ike_status": ike_state,
                    "tunnel_status": tunnel_status,
                    "has_child_sa": has_child,
                    "status": "ESTABLISHED" if tunnel_status == "UP" else ike_state,
                    "uptime": up.group(1).strip() if up else None,
                    "local_ts": lts.group(1).strip() if lts else None,
                    "remote_ts": rts.group(1).strip() if rts else None,
                    "bytes_in": int(bi.group(1)) if bi else None,
                    "bytes_out": int(bo.group(1)) if bo else None,
                    "rekey_time": rk.group(1) if rk else None,
                    "remote_host": remote_host if tunnel_status == "UP" else None,
                    "error_hint": None,
                    "active_paths": 1 if tunnel_status == "UP" else 0,
                }
                by_conn[conn_name] = entry
            else:
                if tunnel_status == "UP":
                    entry["active_paths"] += 1
                # keep the healthiest SA's headline status/details
                if rank[tunnel_status] > rank[entry["tunnel_status"]]:
                    entry["ike_status"] = ike_state
                    entry["tunnel_status"] = tunnel_status
                    entry["has_child_sa"] = has_child
                    entry["status"] = "ESTABLISHED" if tunnel_status == "UP" else ike_state
                    if tunnel_status == "UP":
                        entry["remote_host"] = remote_host
                        if up:
                            entry["uptime"] = up.group(1).strip()
                # sum bytes across the active paths
                if bi:
                    entry["bytes_in"] = (entry["bytes_in"] or 0) + int(bi.group(1))
                if bo:
                    entry["bytes_out"] = (entry["bytes_out"] or 0) + int(bo.group(1))

        for entry in by_conn.values():
            if entry["tunnel_status"] == "IKE_ONLY":
                entry["error_hint"] = "IKE established but tunnel not up. Check ESP cipher compatibility."
            result["connections"].append(entry)
            result["total_connections"] += 1
            if entry["tunnel_status"] == "UP":
                result["active_tunnels"] += 1

        return result

    async def update_connection_statuses(self) -> None:
        """Update all connection statuses from StrongSwan"""
        status = await self.get_status()

        connections, _ = await self.list_connections()
        conn_statuses = {c["name"]: c for c in status.get("connections", [])}

        for conn in connections:
            if conn.name in conn_statuses:
                conn_status = conn_statuses[conn.name]
                tunnel_status = conn_status.get("tunnel_status", "DOWN")

                if tunnel_status == "UP":
                    conn.status = IPsecStatus.ACTIVE
                    conn.last_error = None
                elif tunnel_status == "IKE_ONLY":
                    conn.status = IPsecStatus.ERROR
                    conn.last_error = conn_status.get("error_hint", "IKE established but Child SA failed")
                elif tunnel_status == "CONNECTING":
                    conn.status = IPsecStatus.CONNECTING
                else:
                    conn.status = IPsecStatus.INACTIVE
            else:
                if conn.is_enabled:
                    conn.status = IPsecStatus.INACTIVE
            conn.last_status_check = datetime.utcnow()

        await self.db.commit()

    # ==================== Utility Methods ====================

    async def get_preview(self) -> Dict[str, str]:
        """Get preview of generated configs without applying"""
        return {
            "ipsec_conf": await self.generate_ipsec_conf(),
            "ipsec_secrets": await self.generate_ipsec_secrets()
        }

    async def check_strongswan_installed(self) -> bool:
        """Check if StrongSwan is installed and ipsec-agent is running"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.agent_url}/health")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("ipsec_installed", False)
                return False
        except Exception:
            return False

    async def get_strongswan_version(self) -> Optional[str]:
        """Get StrongSwan version"""
        success, output = await self._run_ipsec_command_async(["version"])
        if success:
            return output.split('\n')[0] if output else None
        return None

    async def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed IPsec status (raw ipsec statusall output)"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.agent_url}/statusall",
                    headers={"Authorization": f"Bearer {self.agent_token}"}
                )

                if response.status_code == 401:
                    return {"success": False, "output": "Unauthorized - check IPSEC_AGENT_TOKEN"}

                if response.status_code != 200:
                    return {"success": False, "output": f"Agent returned status {response.status_code}"}

                return response.json()

        except httpx.ConnectError:
            return {"success": False, "output": "Cannot connect to ipsec-agent"}
        except httpx.TimeoutException:
            return {"success": False, "output": "Timeout connecting to ipsec-agent"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    async def get_logs(self, lines: int = 100, connection: Optional[str] = None) -> Dict[str, Any]:
        """Get recent IPsec/StrongSwan logs, optionally filtered by connection name"""
        try:
            params = {"lines": str(lines)}
            if connection:
                params["connection"] = connection

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.agent_url}/logs",
                    headers={"Authorization": f"Bearer {self.agent_token}"},
                    params=params
                )

                if response.status_code == 401:
                    return {"success": False, "logs": "Unauthorized - check IPSEC_AGENT_TOKEN", "source": None}

                if response.status_code != 200:
                    return {"success": False, "logs": f"Agent returned status {response.status_code}", "source": None}

                return response.json()

        except httpx.ConnectError:
            return {"success": False, "logs": "Cannot connect to ipsec-agent", "source": None}
        except httpx.TimeoutException:
            return {"success": False, "logs": "Timeout connecting to ipsec-agent", "source": None}
        except Exception as e:
            return {"success": False, "logs": str(e), "source": None}

    def get_server_network_info(self) -> Dict[str, Any]:
        """Get server network information for IPsec configuration.

        For AWS EC2, uses the instance metadata service to get accurate host IPs.
        Falls back to container network info if metadata is unavailable.
        """
        import ipaddress
        import os

        info = {
            "private_ip": None,
            "public_ip": None,
            "local_subnet": None,
            "interface": None
        }

        # Check for environment variable overrides first (useful for custom setups)
        if os.environ.get("VPN_SERVER_PRIVATE_IP"):
            info["private_ip"] = os.environ.get("VPN_SERVER_PRIVATE_IP")
        if os.environ.get("VPN_SERVER_PUBLIC_IP"):
            info["public_ip"] = os.environ.get("VPN_SERVER_PUBLIC_IP")
        if os.environ.get("VPN_SERVER_SUBNET"):
            info["local_subnet"] = os.environ.get("VPN_SERVER_SUBNET")

        try:
            # For AWS EC2: Use IMDSv2 (Instance Metadata Service v2)
            # First get a token
            token = None
            try:
                result = subprocess.run(
                    ["curl", "-s", "-X", "PUT",
                     "-H", "X-aws-ec2-metadata-token-ttl-seconds: 60",
                     "--connect-timeout", "2",
                     "http://169.254.169.254/latest/api/token"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout:
                    token = result.stdout.strip()
            except Exception:
                pass

            # Build curl headers for metadata requests
            metadata_headers = []
            if token:
                metadata_headers = ["-H", f"X-aws-ec2-metadata-token: {token}"]

            # Get private IP from EC2 metadata
            if not info["private_ip"]:
                try:
                    cmd = ["curl", "-s", "--connect-timeout", "2"] + metadata_headers + \
                          ["http://169.254.169.254/latest/meta-data/local-ipv4"]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout:
                        ip = result.stdout.strip()
                        if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                            info["private_ip"] = ip
                except Exception:
                    pass

            # Get public IP from EC2 metadata
            if not info["public_ip"]:
                try:
                    cmd = ["curl", "-s", "--connect-timeout", "2"] + metadata_headers + \
                          ["http://169.254.169.254/latest/meta-data/public-ipv4"]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout and not result.stdout.startswith('<?'):
                        ip = result.stdout.strip()
                        if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                            info["public_ip"] = ip
                except Exception:
                    pass

            # Get VPC CIDR / subnet from EC2 metadata (MAC address -> subnet)
            if not info["local_subnet"] and info["private_ip"]:
                try:
                    # First get MAC address
                    cmd = ["curl", "-s", "--connect-timeout", "2"] + metadata_headers + \
                          ["http://169.254.169.254/latest/meta-data/mac"]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout:
                        mac = result.stdout.strip()
                        # Get subnet CIDR using MAC
                        cmd = ["curl", "-s", "--connect-timeout", "2"] + metadata_headers + \
                              [f"http://169.254.169.254/latest/meta-data/network/interfaces/macs/{mac}/subnet-ipv4-cidr-block"]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        if result.returncode == 0 and result.stdout:
                            subnet = result.stdout.strip()
                            if '/' in subnet:
                                info["local_subnet"] = subnet
                except Exception:
                    pass

            # Fallback: Calculate subnet from private IP if we have IP but no subnet
            if info["private_ip"] and not info["local_subnet"]:
                try:
                    # Assume /24 as a reasonable default for most VPC subnets
                    ip_obj = ipaddress.ip_address(info["private_ip"])
                    network = ipaddress.ip_network(f"{info['private_ip']}/24", strict=False)
                    info["local_subnet"] = str(network)
                except Exception:
                    pass

            # Fallback for public IP: use external service
            if not info["public_ip"]:
                try:
                    result = subprocess.run(
                        ["curl", "-s", "--connect-timeout", "5", "https://api.ipify.org"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0 and result.stdout:
                        ip = result.stdout.strip()
                        if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                            info["public_ip"] = ip
                except Exception:
                    pass

            # Set interface name (informational)
            info["interface"] = "eth0"

        except Exception as e:
            logger.error(f"Failed to get server network info: {e}")

        return info
