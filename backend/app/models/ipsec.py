"""
IPsec Connection Model for StrongSwan Site-to-Site VPN
"""
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text,
    ForeignKey, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.session import Base


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
            lines = [
                f'{self.left_id} {self.right_id} : PSK "{self.psk}"',
                f'{self.right_id} {self.left_id} : PSK "{self.psk}"',
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
        # legacy DPDAction -> swanctl child dpd_action ('hold' has no swanctl equivalent)
        return {
            "restart": "restart", "clear": "clear", "hold": "trap", "none": "none",
        }.get(self.dpd_action.value, "restart")

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

        return "\n".join([
            f"    {self.name} {{",
            f"        version = {self._swanctl_version()}",
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
        ])

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
            lines = [f"    ike-{self.name} {{"]
            for i, rid in enumerate(ids, 1):
                lines.append(f"        id-{i} = {rid}")
            lines.append(f'        secret = "{self.psk}"')
            lines.append("    }")
            return "\n".join(lines)
        return ""
