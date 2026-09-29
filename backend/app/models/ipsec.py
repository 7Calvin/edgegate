"""
IPsec Connection Model for StrongSwan Site-to-Site VPN
"""
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Integer,
    ForeignKey, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.session import Base


def _escape_secret(value: str) -> str:
    """Escape a value for a double-quoted strongswan secret (ipsec.secrets /
    swanctl `secrets {}`). Backslash MUST be escaped first, then the double quote,
    so an arbitrary PSK (including `"` or `\\`) is written safely and can't break
    out of the quoted string. Newlines/control chars are rejected upstream in the
    schema (they can't be represented on a single-line directive)."""
    if value is None:
        return value
    return value.replace("\\", "\\\\").replace('"', '\\"')


# Vendor capability registry. The peer's vendor drives the connection's
# capabilities so advanced/route-based behaviour is only ever produced for a vendor
# we've actually validated end-to-end:
#   * fortigate -> route-based (deterministic failover via XFRM), dual-link allowed,
#                  FortiGate export. VALIDATED.
#   * generic   -> policy-based, single-link (no dual/backup), generic export sheet.
# forwarding_mode is DERIVED from this table (the user no longer picks it); the
# forwarding_mode column stays the runtime source of truth for config generation.
# New validated vendors are added here as they're qualified.
VENDOR_CAPABILITIES = {
    "fortigate": {"forwarding_mode": "route", "dual_link": True, "export": "fortigate"},
    "generic": {"forwarding_mode": "policy", "dual_link": False, "export": "generic"},
}
DEFAULT_VENDOR = "fortigate"


def vendor_caps(vendor: str) -> dict:
    """Capabilities for a vendor, falling back to 'generic' for unknown values so a
    bad/legacy value can never accidentally unlock advanced behaviour."""
    return VENDOR_CAPABILITIES.get((vendor or "").strip().lower(), VENDOR_CAPABILITIES["generic"])


class IPsecStatus(str, enum.Enum):
    """IPsec connection status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONNECTING = "connecting"
    ERROR = "error"


class IKEVersion(str, enum.Enum):
    """IKE version"""
    IKEV1 = "ikev1"
    IKEV2 = "ikev2"


class DPDAction(str, enum.Enum):
    """Dead Peer Detection action"""
    RESTART = "restart"
    CLEAR = "clear"
    HOLD = "hold"
    NONE = "none"


class IPsecConnection(Base):
    """IPsec Site-to-Site Connection"""

    __tablename__ = "ipsec_connections"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Connection identification
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text)

    # Local (Left) - This server/gateway
    left_ip = Column(String(45), nullable=False)  # Private IP of gateway
    left_subnet = Column(String(500), nullable=False)  # Local network CIDR(s), comma-separated
    left_id = Column(String(100), nullable=False)  # Public IP or FQDN

    # Remote (Right) - Client/peer
    right_ip = Column(String(45), nullable=False)  # Public IP of peer
    right_ip_backup = Column(String(45), nullable=True)  # 2nd peer IP for HA/failover (swanctl remote_addrs)
    right_subnet = Column(String(500), nullable=False)  # Remote network CIDR(s), comma-separated
    right_id = Column(String(100), nullable=False)  # Peer ID (usually same as right_ip)

    # Authentication
    auth_method = Column(String(20), default="psk")  # psk or pubkey
    psk = Column(Text)  # Pre-shared key (should be encrypted in production)

    # IKE Settings (Phase 1)
    ike_version = Column(
        SQLEnum(IKEVersion, name="ike_version", values_callable=lambda x: [e.value for e in x]),
        default=IKEVersion.IKEV2
    )
    ike_cipher = Column(String(100), default="aes256-sha256-modp2048")
    ike_lifetime = Column(String(20), default="8h")

    # ESP Settings (Phase 2) - No PFS by default for better compatibility
    esp_cipher = Column(String(100), default="aes256-sha256")
    key_lifetime = Column(String(20), default="1h")

    # Control settings
    auto_start = Column(Boolean, default=True)  # auto=start vs auto=add
    # HA/failover: prefer the backup endpoint (orders remote_addrs = [backup, primary]).
    # A manual "switch to backup" sets this True; "rollback to primary" sets it False.
    prefer_backup = Column(Boolean, default=False)
    dpd_action = Column(
        SQLEnum(DPDAction, name="dpd_action", values_callable=lambda x: [e.value for e in x]),
        default=DPDAction.RESTART
    )

    # Forwarding mode:
    #   'policy' -> classic policy-based IPsec: ONE connection with
    #               remote_addrs=[primary,backup] (see to_swanctl). The peer's two
    #               tunnels share one reqid/kernel policy, so the outbound (return)
    #               path follows the last-installed CHILD_SA and OSCILLATES on rekey.
    #   'route'  -> route-based via XFRM interfaces: ONE connection per peer endpoint,
    #               each bound to its own if_id (see to_swanctl_routebased). Routing
    #               metric picks the active path -> primary is deterministic and
    #               failover happens only on real failure. Default kept 'policy' for
    #               backward compatibility; flip per-connection (or change the default)
    #               to adopt route-based.
    forwarding_mode = Column(String(10), default="route", server_default="policy")
    # Peer vendor -> drives forwarding_mode + dual-link availability + export template
    # via VENDOR_CAPABILITIES. See that table. server_default 'generic' keeps any
    # pre-migration row on the safe/simple path; the 018 migration backfills existing
    # route-based rows to 'fortigate'.
    vendor = Column(String(20), default=DEFAULT_VENDOR, server_default="generic")
    # Route-based only: base XFRM interface id. The primary path uses if_id_base and
    # the backup path uses if_id_base + 1. Allocated on create (must be globally unique
    # on the host); see IPsecService._allocate_if_id_base().
    if_id_base = Column(Integer, nullable=True)

    # Status
    status = Column(
        SQLEnum(IPsecStatus, name="ipsec_status", values_callable=lambda x: [e.value for e in x]),
        default=IPsecStatus.INACTIVE
    )
    is_enabled = Column(Boolean, default=True, index=True)
    last_status_check = Column(DateTime(timezone=True))
    last_error = Column(Text)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<IPsecConnection {self.name} ({self.right_ip})>"

    def to_ipsec_conf(self) -> str:
        """Generate ipsec.conf connection block(s)

        If multiple subnets are specified (comma-separated), generates:
        - A base connection with auto=ignore
        - Child connections for each subnet pair using also= inheritance
        """
        left_subnets = [s.strip() for s in self.left_subnet.split(',')]
        right_subnets = [s.strip() for s in self.right_subnet.split(',')]

        # Single subnet on each side - simple config
        if len(left_subnets) == 1 and len(right_subnets) == 1:
            return self._generate_single_conn()

        # Multiple subnets - use base connection with inheritance
        return self._generate_multi_subnet_conf(left_subnets, right_subnets)

    def _generate_single_conn(self) -> str:
        """Generate single connection block (no multiple subnets)"""
        lines = [
            f'conn {self.name}',
            f'    dpdaction={self.dpd_action.value}',
            f'    left={self.left_ip}',
            f'    leftsubnet={self.left_subnet}',
            f'    leftid={self.left_id}',
            f'    leftupdown=/etc/ipsec.d/mss-clamp.sh',
            f'    right={self.right_ip}',
            f'    rightsubnet={self.right_subnet}',
            f'    rightid={self.right_id}',
            f'    leftauth={self.auth_method}',
            f'    rightauth={self.auth_method}',
            f'    ike={self.ike_cipher}!',
            f'    ikelifetime={self.ike_lifetime}',
            f'    esp={self.esp_cipher}!',
            f'    keylife={self.key_lifetime}',
            f'    auto={"start" if self.auto_start else "add"}',
            f'    keyexchange={self.ike_version.value}',
        ]
        return '\n'.join(lines)

    def _generate_multi_subnet_conf(self, left_subnets: list, right_subnets: list) -> str:
        """Generate base connection + child connections for multiple subnets"""
        auto_mode = "start" if self.auto_start else "add"

        # Base connection with shared settings (auto=ignore)
        # Keeps the original name as the base/template
        lines = [
            f'# Base connection: {self.name}',
            f'conn {self.name}',
            f'    dpdaction={self.dpd_action.value}',
            f'    left={self.left_ip}',
            f'    leftid={self.left_id}',
            f'    leftupdown=/etc/ipsec.d/mss-clamp.sh',
            f'    right={self.right_ip}',
            f'    rightid={self.right_id}',
            f'    leftauth={self.auth_method}',
            f'    rightauth={self.auth_method}',
            f'    ike={self.ike_cipher}!',
            f'    ikelifetime={self.ike_lifetime}',
            f'    esp={self.esp_cipher}!',
            f'    keylife={self.key_lifetime}',
            f'    keyexchange={self.ike_version.value}',
            f'    auto=ignore',
            '',
        ]

        # Generate child connections for each subnet combination
        conn_num = 1
        for left_net in left_subnets:
            for right_net in right_subnets:
                lines.extend([
                    f'# {self.name}: {left_net} <-> {right_net}',
                    f'conn {self.name}-{conn_num}',
                    f'    also={self.name}',
                    f'    leftsubnet={left_net}',
                    f'    rightsubnet={right_net}',
                    f'    auto={auto_mode}',
                    '',
                ])
                conn_num += 1

        return '\n'.join(lines).rstrip()

    def to_ipsec_secret(self) -> str:
        """Generate ipsec.secrets lines using leftid and rightid for PSK lookup"""
        if self.auth_method == "psk" and self.psk:
            # StrongSwan looks up PSK by leftid/rightid in both directions
            # Adding both directions ensures PSK is found regardless of initiator
            psk = _escape_secret(self.psk)
            lines = [
                f'{self.left_id} {self.right_id} : PSK "{psk}"',
                f'{self.right_id} {self.left_id} : PSK "{psk}"',
            ]
            return '\n'.join(lines)
        return ""

    # ==================== swanctl (vici) generation ====================
    # The stack is migrating from the legacy stroke/ipsec.conf to swanctl. These
    # produce the swanctl.conf `connections {}` / `secrets {}` entries. HA/failover
    # (a second remote endpoint) plugs into `remote_addrs` below.

    def _swanctl_version(self) -> str:
        return "1" if self.ike_version == IKEVersion.IKEV1 else "2"

    def _swanctl_start_action(self) -> str:
        # auto=start -> initiate on load; auto=add -> install a trap (initiate on traffic)
        return "start" if self.auto_start else "trap"

    def _swanctl_dpd_action(self) -> str:
        # legacy DPDAction -> swanctl child dpd_action. swanctl's canonical values are
        # clear | trap | start; the old "restart" (reinitiate on dead peer) IS swanctl
        # "start", and "hold" IS "trap". Emit the canonical names so the config is valid
        # on every strongSwan version (6.0.4 tolerates "restart" and shows "start", but
        # older/other builds may reject it and silently fall back -> no failover).
        return {
            "restart": "start", "clear": "clear", "hold": "trap", "none": "clear",
        }.get(self.dpd_action.value, "start")

    def _remote_id(self) -> str:
        # right_id is often left blank; strongSwan then keys off the peer IP.
        return self.right_id or self.right_ip

    def _remote_addrs(self) -> str:
        """Comma-separated remote endpoints for swanctl `remote_addrs` (native
        multi-homing failover). Order = which endpoint charon prefers on initiate:
        primary first normally, backup first when `prefer_backup` (manual switch)."""
        primary = self.right_ip
        backup = (getattr(self, "right_ip_backup", None) or "").strip()
        if backup and backup != primary:
            if getattr(self, "prefer_backup", False):
                return f"{backup}, {primary}"
            return f"{primary}, {backup}"
        return primary

    def failover_peer_ids(self):
        """When this connection has a failover backup, the peer runs TWO tunnels (one per
        WAN) toward us. They MUST present distinct IKE identities — if both send the same
        id, each new tunnel's INITIAL_CONTACT destroys the other on our responder and the
        tunnel flaps every ~DPD interval. Derive a stable, distinct id per path from the
        base peer id (`right_id`), so it's independent of the WAN IPs (which change).

        Returns (primary_id, backup_id), or None for a single-link connection (no war to
        avoid there — one id is fine). The FortiGate export sets these as each phase1's
        `localid`; `to_swanctl_secret()` keys them so the PSK is found for both paths."""
        backup = (getattr(self, "right_ip_backup", None) or "").strip()
        if not backup:
            return None
        base = (self.right_id or self.right_ip or "").strip()
        if not base:
            return None
        return (f"{base}-01", f"{base}-02")

    def to_swanctl(self) -> str:
        """Generate this connection's `<name> { ... }` entry for swanctl.conf's
        `connections {}` block (the service wraps it)."""
        left_subnets = [s.strip() for s in self.left_subnet.split(',') if s.strip()]
        right_subnets = [s.strip() for s in self.right_subnet.split(',') if s.strip()]

        if len(left_subnets) <= 1 and len(right_subnets) <= 1:
            pairs = [(self.left_subnet.strip(), self.right_subnet.strip())]
            child_names = [f"{self.name}-net"]
        else:
            pairs = [(l, r) for l in left_subnets for r in right_subnets]
            child_names = [f"{self.name}-net-{i + 1}" for i in range(len(pairs))]

        children = []
        for cname, (lts, rts) in zip(child_names, pairs):
            children.append("\n".join([
                f"            {cname} {{",
                f"                local_ts = {lts}",
                f"                remote_ts = {rts}",
                f"                esp_proposals = {self.esp_cipher}",
                f"                rekey_time = {self.key_lifetime}",
                f"                dpd_action = {self._swanctl_dpd_action()}",
                f"                start_action = {self._swanctl_start_action()}",
                f"            }}",
            ]))

        # Failover: the peer runs two tunnels (one per WAN) that present distinct ids
        # (see failover_peer_ids). strongSwan's default identity uniqueness (uniqueids=yes)
        # makes each new tunnel's INITIAL_CONTACT delete the other on our responder → the
        # tunnel flaps every ~DPD interval. `unique = no` lets both paths coexist as separate
        # SAs. Only set it for failover connections; single-link keeps the default so a
        # reconnecting peer still replaces its own stale SA.
        has_failover = bool((getattr(self, "right_ip_backup", None) or "").strip())
        header = [
            f"    {self.name} {{",
            f"        version = {self._swanctl_version()}",
        ]
        if has_failover:
            header.append(f"        unique = no")
        header += [
            f"        local_addrs = {self.left_ip}",
            f"        remote_addrs = {self._remote_addrs()}",
            f"        proposals = {self.ike_cipher}",
            f"        rekey_time = {self.ike_lifetime}",
            # Short DPD so a dead primary is detected fast (HA/failover). Paired with the
            # tightened charon retransmit settings, dead-peer detection is ~tens of secs.
            f"        dpd_delay = 10s",
            f"        local {{",
            f"            auth = {self.auth_method}",
            f"            id = {self.left_id}",
            f"        }}",
            f"        remote {{",
            f"            auth = {self.auth_method}",
            # No `id` pin: with a failover backup the peer presents a different IP-id per
            # path, so accept any id here. Security is remote_addrs (source IPs) + the PSK,
            # which is keyed by both peer IPs in the secrets block.
            f"        }}",
            f"        children {{",
            "\n".join(children),
            f"        }}",
            f"    }}",
        ]
        return "\n".join(header)

    def to_swanctl_secret(self) -> str:
        """Generate this connection's `ike-<name> { ... }` entry for swanctl.conf's
        `secrets {}` block. Lists our id AND every possible peer id (explicit right_id,
        the primary IP, and the backup IP) so the PSK is found regardless of which
        endpoint the peer authenticates from — essential for the HA/failover backup.

        Each bare IP is emitted in BOTH forms: address type (`1.2.3.4`) and string/FQDN
        type (`@1.2.3.4`). Some peers (notably a FortiGate with a text "Local ID" set to
        its WAN IP) send an IP-looking identity as an ID_FQDN/KEY_ID, not ID_IPV4_ADDR;
        an address-typed owner won't match it -> "no shared key found" and AUTH fails.
        Emitting both keeps the secret keyed (safe with multiple connections) while
        matching whichever id type the peer presents."""
        if self.auth_method == "psk" and self.psk:
            import ipaddress
            ids: list[str] = []

            def add(v: str) -> None:
                if v and v not in ids:
                    ids.append(v)

            for cand in (self.left_id, self.right_id, self.right_ip,
                         getattr(self, "right_ip_backup", None)):
                c = (cand or "").strip()
                if not c:
                    continue
                add(c)
                if not c.startswith("@"):
                    try:
                        ipaddress.ip_address(c)
                        add(f"@{c}")  # same IP, but as a string identity
                    except ValueError:
                        pass
            # HA/failover: the peer presents a DISTINCT id per path (see failover_peer_ids)
            # so its two tunnels don't destroy each other via INITIAL_CONTACT on our side.
            # Key those derived ids too, or the backup path fails with "no shared key found".
            fo = self.failover_peer_ids()
            if fo:
                for rid in fo:
                    add(rid)
            lines = [f"    ike-{self.name} {{"]
            for i, rid in enumerate(ids, 1):
                lines.append(f"        id-{i} = {rid}")
            lines.append(f'        secret = "{_escape_secret(self.psk)}"')
            lines.append("    }")
            return "\n".join(lines)
        return ""

    # ==================== route-based (XFRM interface) generation ====================
    # Option B. Instead of ONE connection with remote_addrs=[primary,backup] sharing a
    # single kernel policy (which oscillates by rekey — the last-installed CHILD_SA wins
    # the outbound policy), emit ONE connection PER peer endpoint, each bound to its own
    # XFRM interface via if_id_in/out. Routing (metric) picks the active path, so the
    # primary is deterministic and failover only happens on real failure.
    #
    # Validated live on homolog (2026-09-25): swanctl loads if_id_in/out; the local/remote
    # auth blocks MUST be multi-line (inline `local { auth = psk id = x }` does NOT parse);
    # `ip link add <name> type xfrm if_id <N> dev <phys>` + `ip route ... dev <name>` work.

    ROUTE_METRIC_PRIMARY = 100
    ROUTE_METRIC_BACKUP = 200

    def _xfrm_ifname(self, if_id: int) -> str:
        # Linux ifname is <=15 chars; keyed by if_id so it's stable and unique.
        return f"eg-{if_id}"

    def _routebased_paths(self):
        """List of (suffix, remote_ip, if_id, metric) for this connection's tunnels:
        one entry for a single-link conn, two (primary + backup) when right_ip_backup is
        set. `prefer_backup` swaps only the route METRICS (manual switch to backup) — the
        if_ids stay pinned per endpoint."""
        base = self.if_id_base
        primary = (self.right_ip or "").strip()
        backup = (getattr(self, "right_ip_backup", None) or "").strip()
        pref = bool(getattr(self, "prefer_backup", False))
        m_pri = self.ROUTE_METRIC_BACKUP if pref else self.ROUTE_METRIC_PRIMARY
        m_bak = self.ROUTE_METRIC_PRIMARY if pref else self.ROUTE_METRIC_BACKUP
        paths = [("p", primary, base, m_pri)]
        if backup and backup != primary:
            paths.append(("b", backup, base + 1, m_bak))
        return paths

    def _routebased_conn_block(self, suffix: str, remote_ip: str, if_id: int) -> str:
        """One `<name>-<suffix> { ... }` connection bound to a single peer + if_id."""
        left_subnets = [s.strip() for s in self.left_subnet.split(',') if s.strip()]
        right_subnets = [s.strip() for s in self.right_subnet.split(',') if s.strip()]
        if len(left_subnets) <= 1 and len(right_subnets) <= 1:
            pairs = [(self.left_subnet.strip(), self.right_subnet.strip())]
        else:
            pairs = [(l, r) for l in left_subnets for r in right_subnets]

        children = []
        for i, (lts, rts) in enumerate(pairs, 1):
            cname = (f"{self.name}-{suffix}-net" if len(pairs) == 1
                     else f"{self.name}-{suffix}-net-{i}")
            children.append("\n".join([
                f"            {cname} {{",
                f"                local_ts = {lts}",
                f"                remote_ts = {rts}",
                f"                esp_proposals = {self.esp_cipher}",
                f"                rekey_time = {self.key_lifetime}",
                f"                dpd_action = {self._swanctl_dpd_action()}",
                f"                start_action = {self._swanctl_start_action()}",
                # updown hook: on CHILD_SA up/down, add/remove the route to the peer
                # subnet via this path's XFRM interface, so the route METRIC decides the
                # active path and failover happens only on real failure. The ipsec-agent
                # writes this script + the per-if_id metric map (see /routebased/apply).
                f"                updown = /etc/swanctl/rb-updown.sh",
                f"            }}",
            ]))

        return "\n".join([
            f"    {self.name}-{suffix} {{",
            f"        version = {self._swanctl_version()}",
            f"        local_addrs = {self.left_ip}",
            f"        remote_addrs = {remote_ip}",
            f"        if_id_in = {if_id}",
            f"        if_id_out = {if_id}",
            f"        proposals = {self.ike_cipher}",
            f"        rekey_time = {self.ike_lifetime}",
            # Short DPD so a dead path is detected fast; the route is withdrawn on
            # CHILD_SA down (updown) and the other endpoint's metric takes over.
            f"        dpd_delay = 10s",
            f"        local {{",
            f"            auth = {self.auth_method}",
            f"            id = {self.left_id}",
            f"        }}",
            f"        remote {{",
            f"            auth = {self.auth_method}",
            # No id pin: the peer authenticates from a distinct IP-id per WAN; security
            # is remote_addrs (source IP) + PSK, keyed by every peer id in the secret.
            f"        }}",
            f"        children {{",
            "\n".join(children),
            f"        }}",
            f"    }}",
        ])

    def to_swanctl_routebased(self) -> str:
        """Route-based `connections {}` body: `<name>-p` (+ `<name>-b` if a backup peer
        exists), each on its own if_id. Requires if_id_base to be allocated. The
        `secrets {}` block is unchanged — reuse to_swanctl_secret()."""
        if self.if_id_base is None:
            raise ValueError(
                f"IPsec connection '{self.name}': if_id_base not allocated "
                f"(required for forwarding_mode='route')"
            )
        blocks = [self._routebased_conn_block(sfx, ip, ifid)
                  for (sfx, ip, ifid, _metric) in self._routebased_paths()]
        return "\n".join(blocks)

    def xfrm_ifaces(self):
        """Interface/route manifest for the ipsec-agent. For each tunnel path returns
        {ifname, if_id, metric, peer, routes:[remote CIDRs]}. The agent, per entry:
          ip link add <ifname> type xfrm if_id <if_id> dev <phys>; ip link set up
          (per remote CIDR) ip route replace <cidr> dev <ifname> metric <metric>
        and installs the updown hook that withdraws/reinstalls the route on SA down/up
        so metric-based standby fails over on real failure only."""
        right_subnets = [s.strip() for s in self.right_subnet.split(',') if s.strip()]
        return [
            {
                "ifname": self._xfrm_ifname(ifid),
                "if_id": ifid,
                "metric": metric,
                "peer": ip,
                "routes": right_subnets,
            }
            for (_sfx, ip, ifid, metric) in self._routebased_paths()
        ]
