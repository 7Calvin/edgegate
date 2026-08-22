"""
Firewall Service - Manages firewall rules and nftables integration
"""
from typing import Optional, List, Tuple
from datetime import datetime
from uuid import UUID
import subprocess
import tempfile
import logging
from pathlib import Path
import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, or_, and_

from app.models.user import User, UserType
from app.models.firewall import FirewallRule, FirewallAction, ProtocolType, NATRule, NATType
from app.core.config import settings
from app.schemas.firewall import FirewallRuleCreate, FirewallRuleUpdate

logger = logging.getLogger(__name__)


class FirewallService:
    """Firewall rule management and nftables integration"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.engine = settings.FIREWALL_ENGINE  # nftables or iptables
        self.table_name = "vpn_filter"
        self.chain_name = "vpn_rules"

    # ==================== CRUD Operations ====================

    async def get_rule_by_id(self, rule_id: UUID) -> Optional[FirewallRule]:
        """Get firewall rule by ID"""
        result = await self.db.execute(
            select(FirewallRule).where(FirewallRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    async def list_rules(
        self,
        user_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
        include_global: bool = True,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[FirewallRule], int]:
        """
        List firewall rules with filtering.

        Args:
            user_id: Filter by specific user
            is_active: Filter by active status
            include_global: Include global rules (user_id=NULL)
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            (list of rules, total count)
        """
        query = select(FirewallRule)

        # Build filters
        filters = []

        if user_id:
            if include_global:
                filters.append(
                    or_(
                        FirewallRule.user_id == user_id,
                        FirewallRule.user_id.is_(None)
                    )
                )
            else:
                filters.append(FirewallRule.user_id == user_id)
        elif not include_global:
            filters.append(FirewallRule.user_id.isnot(None))

        if is_active is not None:
            filters.append(FirewallRule.is_active == is_active)

        if filters:
            query = query.where(and_(*filters))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.execute(count_query)
        total_count = total.scalar()

        # Apply ordering and pagination
        query = query.order_by(
            FirewallRule.priority,
            FirewallRule.created_at
        ).offset(skip).limit(limit)

        result = await self.db.execute(query)
        rules = result.scalars().all()

        return list(rules), total_count

    async def get_rules_for_user(self, user: User) -> List[FirewallRule]:
        """Get all rules applicable to a specific user"""
        filters = [
            FirewallRule.is_active == True,
            or_(
                FirewallRule.user_id == user.id,
                and_(
                    FirewallRule.user_id.is_(None),
                    or_(
                        and_(
                            FirewallRule.applies_to_human_users == True,
                            user.user_type == UserType.HUMAN
                        ),
                        and_(
                            FirewallRule.applies_to_service_accounts == True,
                            user.user_type == UserType.SERVICE
                        )
                    )
                )
            )
        ]

        result = await self.db.execute(
            select(FirewallRule)
            .where(and_(*filters))
            .order_by(FirewallRule.priority)
        )

        return list(result.scalars().all())

    async def create_rule(
        self,
        data: FirewallRuleCreate,
        created_by: User
    ) -> Tuple[Optional[FirewallRule], Optional[str]]:
        """
        Create a new firewall rule.

        Returns:
            (rule, error_message)
        """
        # Validate scope
        if not data.user_id and not data.applies_to_service_accounts and not data.applies_to_human_users:
            return None, "Rule must have a user_id or apply to service accounts/human users"

        # Check for duplicate names
        existing = await self.db.execute(
            select(FirewallRule).where(
                FirewallRule.name == data.name,
                FirewallRule.user_id == data.user_id
            )
        )
        if existing.scalar_one_or_none():
            return None, f"Rule with name '{data.name}' already exists"

        rule = FirewallRule(
            user_id=data.user_id,
            applies_to_service_accounts=data.applies_to_service_accounts,
            applies_to_human_users=data.applies_to_human_users,
            name=data.name,
            description=data.description,
            action=data.action,
            protocol=data.protocol,
            priority=data.priority,
            source_network=data.source_network,
            source_port_range=data.source_port_range,
            destination_network=data.destination_network,
            destination_port_range=data.destination_port_range,
            rate_limit_connections_per_second=data.rate_limit_connections_per_second,
            created_by_id=created_by.id,
        )

        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)

        logger.info(f"Firewall rule created: {rule.name} by {created_by.username}")
        return rule, None

    async def update_rule(
        self,
        rule: FirewallRule,
        data: FirewallRuleUpdate,
        updated_by: User
    ) -> Tuple[FirewallRule, Optional[str]]:
        """Update a firewall rule"""
        update_data = data.model_dump(exclude_unset=True)

        # System rules can only have is_active toggled
        if rule.is_system_rule:
            allowed_fields = {"is_active"}
            other_fields = set(update_data.keys()) - allowed_fields
            if other_fields:
                return rule, f"System rules can only be enabled/disabled, cannot modify: {', '.join(other_fields)}"

        for field, value in update_data.items():
            setattr(rule, field, value)

        await self.db.commit()
        await self.db.refresh(rule)

        logger.info(f"Firewall rule updated: {rule.name} by {updated_by.username}")
        return rule, None

    async def delete_rule(
        self,
        rule: FirewallRule,
        deleted_by: User
    ) -> Tuple[bool, Optional[str]]:
        """Delete a firewall rule"""
        if rule.is_system_rule:
            return False, "System rules cannot be deleted"

        await self.db.delete(rule)
        await self.db.commit()

        logger.info(f"Firewall rule deleted: {rule.name} by {deleted_by.username}")
        return True, None

    # ==================== NFTables Integration ====================

    async def generate_nftables_config(self, include_input_protection: bool = True) -> str:
        """
        Generate complete nftables configuration.

        Args:
            include_input_protection: Include INPUT chain to protect the VPN server itself
        """
        rules, _ = await self.list_rules(is_active=True)

        lines = [
            "#!/usr/sbin/nft -f",
            "",
            f"# EdgeGate Firewall Rules",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            f"# Total rules: {len(rules)}",
            "",
            f"table inet {self.table_name} {{",
        ]

        # INPUT chain - protect the VPN server itself
        if include_input_protection:
            lines.extend([
                "",
                "    # INPUT chain - protect the VPN server",
                "    chain input {",
                "        type filter hook input priority 0; policy drop;",
                "",
                "        # Allow loopback",
                "        iif lo accept",
                "",
                "        # Allow established/related connections",
                "        ct state established,related accept",
                "",
                "        # Drop invalid packets",
                "        ct state invalid drop",
                "",
                "        # Allow ICMP (ping)",
                "        ip protocol icmp accept",
                "        ip6 nexthdr icmpv6 accept",
                "",
                "        # Allow SSH (adjust port if using non-standard)",
                "        tcp dport 22 accept",
                "",
                "        # Allow HTTPS (API access)",
                "        tcp dport 443 accept",
                "",
                "        # Allow HTTP (optional, for redirect to HTTPS)",
                "        tcp dport 80 accept",
                "",
                "        # Allow OpenVPN",
                f"        udp dport {settings.OPENVPN_PORT} accept",
                f"        tcp dport {settings.OPENVPN_PORT} accept",
                "",
                "        # Allow OpenVPN management interface (localhost only)",
                "        tcp dport 7505 ip saddr 127.0.0.1 accept",
                "",
                "        # Allow connections from VPN clients to server",
                f"        ip saddr {settings.OPENVPN_NETWORK}/{settings.OPENVPN_NETMASK_CIDR} accept",
                "",
                "        # Log and drop everything else",
                "        # log prefix \"[NFT INPUT DROP] \" drop",
                "        drop",
                "    }",
                "",
                "    # OUTPUT chain - allow all outbound",
                "    chain output {",
                "        type filter hook output priority 0; policy accept;",
                "    }",
            ])

        # FORWARD chain - VPN traffic rules
        lines.extend([
            "",
            f"    # FORWARD chain - VPN traffic filtering",
            f"    chain {self.chain_name} {{",
            "        type filter hook forward priority 0; policy drop;",
            "",
            "        # Allow established connections",
            "        ct state established,related accept",
            "",
            "        # Drop invalid packets",
            "        ct state invalid drop",
            "",
        ])

        # Add user rules sorted by priority
        for rule in sorted(rules, key=lambda r: r.priority):
            nft_rule = self._rule_to_nftables(rule)
            if nft_rule:
                comment = f"# {rule.name}"
                if rule.description:
                    comment += f" - {rule.description[:50]}"
                lines.append(f"        {comment}")
                lines.append(f"        {nft_rule}")
                lines.append("")

        lines.extend([
            "        # Default policy",
            f"        {settings.FIREWALL_DEFAULT_POLICY}",
            "    }",
            "}",
            "",
        ])

        return "\n".join(lines)

    def _rule_to_nftables(self, rule: FirewallRule) -> Optional[str]:
        """Convert a FirewallRule to nftables syntax"""
        parts = []

        # Source network
        if rule.source_network:
            if "," in rule.source_network:
                # Multiple networks - use nftables set syntax
                networks = rule.source_network.replace(" ", "")
                parts.append(f"ip saddr {{ {networks} }}")
            else:
                parts.append(f"ip saddr {rule.source_network}")

        # Destination network
        if rule.destination_network:
            if "," in rule.destination_network:
                # Multiple networks - use nftables set syntax
                networks = rule.destination_network.replace(" ", "")
                parts.append(f"ip daddr {{ {networks} }}")
            else:
                parts.append(f"ip daddr {rule.destination_network}")

        # Protocol
        if rule.protocol != ProtocolType.ALL:
            # ICMP needs special handling in nftables
            if rule.protocol == ProtocolType.ICMP:
                parts.append("ip protocol icmp")
            else:
                parts.append(rule.protocol.value)

            # Source port (not applicable for ICMP)
            if rule.protocol != ProtocolType.ICMP and rule.source_port_range:
                port_expr = self._parse_port_range(rule.source_port_range)
                parts.append(f"sport {port_expr}")

            # Destination port (not applicable for ICMP)
            if rule.protocol != ProtocolType.ICMP and rule.destination_port_range:
                port_expr = self._parse_port_range(rule.destination_port_range)
                parts.append(f"dport {port_expr}")

        # Rate limiting
        if rule.action == FirewallAction.LIMIT and rule.rate_limit_connections_per_second:
            parts.append(f"limit rate {rule.rate_limit_connections_per_second}/second")

        # Action
        action_map = {
            FirewallAction.ACCEPT: "accept",
            FirewallAction.DROP: "drop",
            FirewallAction.REJECT: "reject",
            FirewallAction.LIMIT: "accept",  # Limit implies accept if within rate
        }
        parts.append(action_map[rule.action])

        return " ".join(parts)

    def _parse_port_range(self, port_str: str) -> str:
        """Parse port range string to nftables format"""
        # Handle comma-separated ports
        if "," in port_str:
            return "{ " + port_str.replace(",", ", ") + " }"

        # Handle range (e.g., "1000-2000")
        if "-" in port_str:
            start, end = port_str.split("-")
            return f"{start}-{end}"

        # Single port
        return port_str

    async def apply_rules(self) -> Tuple[bool, Optional[str]]:
        """Apply firewall rules to the OpenVPN container"""
        try:
            script = "/opt/openvpn-scripts/apply-firewall.sh"

            # --- 1. Handle block-client-to-client rule ---
            result = await self.db.execute(
                select(FirewallRule).where(FirewallRule.name == "block-client-to-client")
            )
            block_c2c_rule = result.scalar_one_or_none()

            # If block-client-to-client rule exists and is active → block (disable c2c)
            # If rule doesn't exist → allow (enable c2c)
            if block_c2c_rule and block_c2c_rule.is_active:
                c2c_action = "client-to-client-disable"
            else:
                c2c_action = "client-to-client-enable"

            c2c_result = subprocess.run(
                ["docker", "exec", "edgegate-openvpn", script, c2c_action],
                capture_output=True,
                text=True,
                timeout=30
            )
            if c2c_result.returncode != 0:
                logger.warning(f"Failed to {c2c_action}: {c2c_result.stderr}")
            else:
                logger.info(f"Client-to-client: {c2c_action}")

            # --- 2. Handle allow-internal-network rule ---
            result = await self.db.execute(
                select(FirewallRule).where(FirewallRule.name == "allow-internal-network")
            )
            internal_rule = result.scalar_one_or_none()

            # Clear existing allowed networks first
            clear_result = subprocess.run(
                ["docker", "exec", "edgegate-openvpn", script, "clear"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if clear_result.returncode != 0:
                logger.warning(f"Failed to clear firewall rules: {clear_result.stderr}")

            # If allow-internal-network is active, add the configured networks
            if internal_rule and internal_rule.is_active and internal_rule.destination_network:
                networks = str(internal_rule.destination_network)
                # Handle comma-separated networks
                for network in networks.split(","):
                    network = network.strip()
                    if network:
                        add_result = subprocess.run(
                            ["docker", "exec", "edgegate-openvpn", script, "add", network],
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        if add_result.returncode != 0:
                            logger.warning(f"Failed to add network {network}: {add_result.stderr}")
                        else:
                            logger.info(f"Added network {network} to allowed list")
            else:
                # Just reload with empty allowed networks (block all private)
                reload_result = subprocess.run(
                    ["docker", "exec", "edgegate-openvpn", script, "reload"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if reload_result.returncode != 0:
                    logger.warning(f"Failed to reload firewall: {reload_result.stderr}")

            logger.info("Firewall rules applied to OpenVPN container")
            return True, None

        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"Failed to apply firewall rules: {e}")
            return False, str(e)

    async def _apply_nftables(self) -> Tuple[bool, Optional[str]]:
        """Apply rules using nftables"""
        try:
            config = await self.generate_nftables_config()

            # Write to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.nft',
                delete=False
            ) as f:
                f.write(config)
                config_file = f.name

            try:
                # Validate configuration
                result = subprocess.run(
                    ["nft", "-c", "-f", config_file],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    return False, f"Configuration validation failed: {result.stderr}"

                # Apply configuration
                result = subprocess.run(
                    ["nft", "-f", config_file],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    return False, f"Failed to apply rules: {result.stderr}"

                logger.info("Firewall rules applied successfully")
                return True, None

            finally:
                Path(config_file).unlink(missing_ok=True)

        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except FileNotFoundError:
            return False, "nft command not found"
        except Exception as e:
            logger.error(f"Failed to apply nftables rules: {e}")
            return False, str(e)

    async def _apply_iptables(self) -> Tuple[bool, Optional[str]]:
        """Apply rules using iptables (legacy fallback)"""
        try:
            rules, _ = await self.list_rules(is_active=True)

            # Flush existing VPN chain
            subprocess.run(
                ["iptables", "-F", "VPN_RULES"],
                capture_output=True,
                timeout=10
            )

            # Create chain if not exists
            subprocess.run(
                ["iptables", "-N", "VPN_RULES"],
                capture_output=True,
                timeout=10
            )

            # Add rules
            for rule in sorted(rules, key=lambda r: r.priority):
                cmd = self._rule_to_iptables(rule)
                if cmd:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode != 0:
                        logger.warning(f"Failed to add rule {rule.name}: {result.stderr}")

            logger.info("iptables rules applied successfully")
            return True, None

        except Exception as e:
            logger.error(f"Failed to apply iptables rules: {e}")
            return False, str(e)

    def _rule_to_iptables(self, rule: FirewallRule) -> Optional[List[str]]:
        """Convert a FirewallRule to iptables command"""
        cmd = ["iptables", "-A", "VPN_RULES"]

        if rule.source_network:
            cmd.extend(["-s", str(rule.source_network)])

        if rule.destination_network:
            cmd.extend(["-d", str(rule.destination_network)])

        if rule.protocol != ProtocolType.ALL:
            cmd.extend(["-p", rule.protocol.value])

            if rule.destination_port_range:
                if "," in rule.destination_port_range:
                    cmd.extend(["-m", "multiport", "--dports", rule.destination_port_range])
                else:
                    cmd.extend(["--dport", rule.destination_port_range])

        action_map = {
            FirewallAction.ACCEPT: "ACCEPT",
            FirewallAction.DROP: "DROP",
            FirewallAction.REJECT: "REJECT",
            FirewallAction.LIMIT: "ACCEPT",
        }
        cmd.extend(["-j", action_map[rule.action]])

        return cmd

    # ==================== NAT Configuration ====================

    async def _get_nat_rules(self) -> List[NATRule]:
        """Get all active NAT rules from database"""
        result = await self.db.execute(
            select(NATRule).where(NATRule.is_active == True)
        )
        return list(result.scalars().all())

    async def generate_nat_config(self) -> str:
        """
        Generate nftables NAT configuration.

        Includes:
        - DNAT rules for port forwarding (from database)
        - SNAT/MASQUERADE for public interface (internet access)
        """
        nat_rules = await self._get_nat_rules()

        lines = [
            "#!/usr/sbin/nft -f",
            "",
            "# NAT Configuration for EdgeGate",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            f"# Public interface: {settings.PUBLIC_INTERFACE}",
            f"# VPN Network: {settings.OPENVPN_NETWORK}/{settings.OPENVPN_NETMASK_CIDR}",
            "",
            "table ip nat {",
            "    chain prerouting {",
            "        type nat hook prerouting priority dstnat; policy accept;",
            "",
        ]

        # Add DNAT rules for port forwarding
        dnat_rules = [r for r in nat_rules if r.nat_type == NATType.DNAT]
        if dnat_rules:
            lines.append("        # DNAT rules (port forwarding)")
            for rule in dnat_rules:
                proto = rule.protocol.value if rule.protocol and rule.protocol != ProtocolType.ALL else "tcp"
                comment = f"# {rule.name}"
                if rule.description:
                    comment += f" - {rule.description[:40]}"
                lines.append(f"        {comment}")

                rule_parts = []
                if rule.source_network:
                    rule_parts.append(f"ip saddr {rule.source_network}")
                rule_parts.append(proto)
                rule_parts.append(f"dport {rule.external_port}")
                rule_parts.append(f"dnat to {rule.internal_ip}:{rule.internal_port}")

                lines.append(f"        {' '.join(rule_parts)}")
                lines.append("")

        lines.extend([
            "    }",
            "",
            "    chain postrouting {",
            "        type nat hook postrouting priority srcnat; policy accept;",
            "",
            f"        # SNAT/MASQUERADE for internet access via {settings.PUBLIC_INTERFACE}",
            f"        ip saddr {settings.OPENVPN_NETWORK}/{settings.OPENVPN_NETMASK_CIDR} "
            f"oifname \"{settings.PUBLIC_INTERFACE}\" masquerade",
            "    }",
            "}",
            "",
        ])

        return "\n".join(lines)

    async def apply_nat_rules(self) -> Tuple[bool, Optional[str]]:
        """Apply NAT rules to the system using nftables"""
        try:
            config = await self.generate_nat_config()

            # Write to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.nft',
                delete=False
            ) as f:
                f.write(config)
                config_file = f.name

            try:
                # Validate configuration
                result = subprocess.run(
                    ["nft", "-c", "-f", config_file],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    return False, f"NAT configuration validation failed: {result.stderr}"

                # Remove existing nat table first (if exists)
                subprocess.run(
                    ["nft", "delete", "table", "ip", "nat"],
                    capture_output=True,
                    timeout=10
                )

                # Apply configuration
                result = subprocess.run(
                    ["nft", "-f", config_file],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    return False, f"Failed to apply NAT rules: {result.stderr}"

                logger.info("NAT rules applied successfully")
                return True, None

            finally:
                Path(config_file).unlink(missing_ok=True)

        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except FileNotFoundError:
            return False, "nft command not found - falling back to iptables"
        except Exception as e:
            logger.error(f"Failed to apply NAT rules: {e}")
            return False, str(e)

    async def apply_nat_rules_iptables(self) -> Tuple[bool, Optional[str]]:
        """Apply NAT rules using iptables (legacy fallback)"""
        try:
            nat_rules = await self._get_nat_rules()

            # Setup MASQUERADE for public interface
            vpn_network = f"{settings.OPENVPN_NETWORK}/{settings.OPENVPN_NETMASK_CIDR}"

            # MASQUERADE for public interface (internet)
            subprocess.run([
                "iptables", "-t", "nat", "-C", "POSTROUTING",
                "-s", vpn_network, "-o", settings.PUBLIC_INTERFACE,
                "-j", "MASQUERADE"
            ], capture_output=True, timeout=10)

            result = subprocess.run([
                "iptables", "-t", "nat", "-A", "POSTROUTING",
                "-s", vpn_network, "-o", settings.PUBLIC_INTERFACE,
                "-j", "MASQUERADE"
            ], capture_output=True, timeout=10)

            # Apply DNAT rules
            for rule in nat_rules:
                if rule.nat_type == NATType.DNAT:
                    proto = rule.protocol.value if rule.protocol else "tcp"
                    cmd = [
                        "iptables", "-t", "nat", "-A", "PREROUTING",
                        "-p", proto,
                        "--dport", str(rule.external_port),
                        "-j", "DNAT",
                        "--to-destination", f"{rule.internal_ip}:{rule.internal_port}"
                    ]

                    if rule.source_network:
                        cmd.extend(["-s", str(rule.source_network)])

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode != 0:
                        logger.warning(f"Failed to add DNAT rule {rule.name}: {result.stderr}")

            logger.info("NAT rules applied via iptables")
            return True, None

        except Exception as e:
            logger.error(f"Failed to apply NAT rules via iptables: {e}")
            return False, str(e)

    async def get_status(self) -> dict:
        """Get firewall status"""
        status = {
            "engine": self.engine,
            "is_active": False,
            "total_rules": 0,
            "active_rules": 0,
            "last_applied_at": None,
        }

        try:
            # Check if firewall is active by querying VPN_FILTER chain in OpenVPN container
            try:
                result = subprocess.run(
                    ["docker", "exec", "edgegate-openvpn", "iptables", "-L", "VPN_FILTER", "-n"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                # If command succeeds and has rules, firewall is active
                status["is_active"] = result.returncode == 0 and "DROP" in result.stdout
            except subprocess.TimeoutExpired:
                logger.warning("Timeout checking firewall status")
                status["is_active"] = False
            except Exception as e:
                logger.warning(f"Failed to check firewall status: {e}")
                status["is_active"] = False

            # Get rule counts
            total_result = await self.db.execute(
                select(func.count(FirewallRule.id))
            )
            status["total_rules"] = total_result.scalar()

            active_result = await self.db.execute(
                select(func.count(FirewallRule.id))
                .where(FirewallRule.is_active == True)
            )
            status["active_rules"] = active_result.scalar()

        except Exception as e:
            logger.error(f"Failed to get firewall status: {e}")

        return status

    # ==================== System Rules ====================

    async def create_default_rules(self) -> None:
        """Create default system rules"""
        default_rules = [
            {
                "name": "allow-icmp",
                "description": "Allow ICMP (ping)",
                "action": FirewallAction.ACCEPT,
                "protocol": ProtocolType.ICMP,
                "priority": 10,
                "applies_to_human_users": True,
                "applies_to_service_accounts": True,
                "is_system_rule": True,
            },
            {
                "name": "allow-dns",
                "description": "Allow DNS queries",
                "action": FirewallAction.ACCEPT,
                "protocol": ProtocolType.UDP,
                "destination_port_range": "53",
                "priority": 20,
                "applies_to_human_users": True,
                "applies_to_service_accounts": True,
                "is_system_rule": True,
            },
            {
                "name": "allow-http-https",
                "description": "Allow HTTP and HTTPS",
                "action": FirewallAction.ACCEPT,
                "protocol": ProtocolType.TCP,
                "destination_port_range": "80,443",
                "priority": 30,
                "applies_to_human_users": True,
                "applies_to_service_accounts": True,
                "is_system_rule": True,
            },
        ]

        for rule_data in default_rules:
            # Check if exists
            existing = await self.db.execute(
                select(FirewallRule).where(
                    FirewallRule.name == rule_data["name"],
                    FirewallRule.is_system_rule == True
                )
            )
            if existing.scalar_one_or_none():
                continue

            rule = FirewallRule(**rule_data)
            self.db.add(rule)

        await self.db.commit()
        logger.info("Default firewall rules created")
