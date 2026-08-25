"""
VPN Service - Manages VPN profiles, certificates, and configurations
"""
from typing import Optional, Tuple, List
from datetime import datetime
from uuid import UUID
import subprocess
import os
import re
import tempfile
import logging
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, delete

from app.models.user import User
from app.models.vpn_profile import VPNProfile, AuthMethod
from app.models.ip_pool import IPPool
from app.core.config import settings
from app.schemas.vpn import VPNProfileCreate, VPNProfileUpdate

logger = logging.getLogger(__name__)

# Server config file path
SERVER_CONFIG_FILE = Path("/app/data/server_config.json")


def get_server_config() -> dict:
    """Load server config from file or return defaults from settings"""
    if SERVER_CONFIG_FILE.exists():
        try:
            return json.loads(SERVER_CONFIG_FILE.read_text())
        except Exception:
            pass

    # Return defaults from settings
    return {
        "server_host": settings.OPENVPN_HOST,
        "server_port": settings.OPENVPN_PORT,
        "protocol": settings.OPENVPN_PROTOCOL,
        "vpn_network": settings.OPENVPN_NETWORK,
        "vpn_netmask": settings.OPENVPN_NETMASK,
        "dns_servers": [settings.OPENVPN_DNS_1, settings.OPENVPN_DNS_2],
        "internal_dns_server": "",
        "split_dns_domains": [],
        "push_routes": [],
        "redirect_gateway": True,
        "compression": False,
        "client_to_client": False,
        "duplicate_cn": False,
        "max_clients": 100,
        "keepalive_interval": 10,
        "keepalive_timeout": 120,
    }


def save_server_config(config: dict) -> bool:
    """Persist server config to file (single source of truth for get_server_config)."""
    try:
        SERVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        SERVER_CONFIG_FILE.write_text(json.dumps(config, indent=2))
        return True
    except Exception as e:
        logger.error(f"Failed to save server config: {e}")
        return False


class VPNService:
    """VPN profile and certificate management service"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.pki_dir = Path(settings.OPENVPN_PKI_DIR)
        self.config_dir = Path(settings.OPENVPN_CONFIG_DIR)
        self.ccd_dir = Path(settings.OPENVPN_CCD_DIR)

    async def get_profile_by_user_id(self, user_id: UUID) -> Optional[VPNProfile]:
        """Get VPN profile for a user"""
        result = await self.db.execute(
            select(VPNProfile).where(VPNProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_profile_by_id(self, profile_id: UUID) -> Optional[VPNProfile]:
        """Get VPN profile by ID"""
        result = await self.db.execute(
            select(VPNProfile).where(VPNProfile.id == profile_id)
        )
        return result.scalar_one_or_none()

    async def create_profile(
        self,
        user: User,
        data: VPNProfileCreate
    ) -> Tuple[Optional[VPNProfile], Optional[str]]:
        """
        Create VPN profile for user with certificates.

        Returns:
            (profile, error_message)
        """
        # Check if user already has a profile
        existing = await self.get_profile_by_user_id(user.id)
        if existing:
            return None, "User already has a VPN profile"

        # Allocate IP address
        ip_address = await self._allocate_ip()
        if not ip_address:
            return None, "No available IP addresses in pool"

        # Generate certificates
        try:
            certs = await self._generate_certificates(user.username)
        except Exception as e:
            logger.error(f"Certificate generation failed: {e}")
            return None, f"Certificate generation failed: {str(e)}"

        # Create profile
        profile = VPNProfile(
            user_id=user.id,
            client_cert=certs["client_cert"],
            client_key=certs["client_key"],
            ca_cert=certs["ca_cert"],
            ta_key=certs.get("ta_key"),
            assigned_ip=ip_address,
            auth_method=data.auth_method,
            allowed_networks=data.allowed_networks,
            denied_networks=data.denied_networks,
            push_routes=data.push_routes,
            push_dns_servers=data.push_dns_servers,
            push_dns_domains=data.push_dns_domains,
            compression=data.compression,
            tcp_mode=data.tcp_mode,
            custom_port=data.custom_port,
            session_timeout_minutes=data.session_timeout_minutes,
            idle_timeout_minutes=data.idle_timeout_minutes,
            max_bandwidth_mbps=data.max_bandwidth_mbps,
        )

        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)

        # Create client-config-dir file for this user
        await self._create_ccd_file(user.username, profile)

        logger.info(f"VPN profile created for user {user.username} with IP {ip_address}")
        return profile, None

    async def update_profile(
        self,
        profile: VPNProfile,
        data: VPNProfileUpdate
    ) -> VPNProfile:
        """Update VPN profile settings"""
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(profile, field, value)

        await self.db.commit()
        await self.db.refresh(profile)

        # Update CCD file if routes changed
        if any(f in update_data for f in ["push_routes", "allowed_networks", "denied_networks"]):
            user = await self._get_user_by_profile(profile)
            if user:
                await self._create_ccd_file(user.username, profile)

        return profile

    async def revoke_profile(
        self,
        profile: VPNProfile,
        revoked_by: User,
        reason: Optional[str] = None
    ) -> bool:
        """Revoke a VPN profile and its certificate"""
        try:
            # Get user for certificate name
            user = await self._get_user_by_profile(profile)
            if user:
                await self._revoke_certificate(user.username)

            profile.is_revoked = True
            profile.revoked_at = datetime.utcnow()
            profile.revoked_by_id = revoked_by.id
            profile.revocation_reason = reason
            profile.is_active = False

            await self.db.commit()

            # Remove CCD file
            if user:
                await self._remove_ccd_file(user.username)

            logger.info(f"VPN profile revoked for user_id={profile.user_id}")
            return True

        except Exception as e:
            logger.error(f"Profile revocation failed: {e}")
            return False

    @staticmethod
    def _client_dns_directives(server_config: dict) -> list:
        """
        DNS directives for a client .ovpn (mirrors update_server_conf_dns).

        Every configured resolver (internal DNS + dns_servers) is pushed to the
        client regardless of tunnel mode, so a DNS IP set here always works whether
        or not redirect-gateway is on. Reachability is what matters, not "public vs
        internal": in split tunnel each resolver also gets a host route so the DNS
        query actually travels through the VPN (the old code dropped DNS in split
        tunnel to avoid "ping IP works, name fails" — pushing a route to the resolver
        fixes that at the root instead). In full tunnel redirect-gateway already
        routes everything, so the host routes are unnecessary.

        The DNS search domain is a resolver suffix and is always pushed when set.
        DOMAIN-ROUTE (split NRPT: force *.domain to the pushed resolver) is only
        meaningful in split tunnel and only when a resolver exists.
        """
        dns_servers = [str(d).strip() for d in (server_config.get("dns_servers") or []) if str(d).strip()]
        redirect_gateway = server_config.get("redirect_gateway", True)
        internal_dns = (server_config.get("internal_dns_server") or "").strip()
        split_domains = [
            str(d).strip().lstrip(".")
            for d in (server_config.get("split_dns_domains") or [])
            if str(d).strip()
        ]

        # Resolvers to push: internal DNS first, then dns_servers, de-duplicated.
        resolvers = []
        for ip in ([internal_dns] if internal_dns else []) + dns_servers:
            if ip and ip not in resolvers:
                resolvers.append(ip)

        lines = []
        for ip in resolvers:
            if not redirect_gateway:
                lines.append(f"route {ip} 255.255.255.255")
            lines.append(f"dhcp-option DNS {ip}")

        if split_domains:
            lines.append(f"dhcp-option DOMAIN {split_domains[0]}")
            if resolvers and not redirect_gateway:
                for d in split_domains:
                    lines.append(f"dhcp-option DOMAIN-ROUTE {d}")
        return lines

    async def generate_ovpn_config(self, profile: VPNProfile) -> str:
        """Generate .ovpn configuration file content"""
        user = await self._get_user_by_profile(profile)
        username = user.username if user else "client"

        # Load server configuration
        server_config = get_server_config()
        server_host = server_config.get("server_host", settings.OPENVPN_HOST)
        server_port = profile.custom_port or server_config.get("server_port", settings.OPENVPN_PORT)
        protocol = server_config.get("protocol", "udp")
        if profile.tcp_mode:
            protocol = "tcp"
        dns_servers = server_config.get("dns_servers", [])
        push_routes = server_config.get("push_routes", [])
        compression = server_config.get("compression", False) or profile.compression

        # Build configuration
        config_lines = [
            "# OpenVPN Client Configuration",
            f"# Generated for: {username}",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            "",
            "client",
            "dev tun",
            f"proto {protocol}",
            f"remote {server_host} {server_port}",
            "resolv-retry infinite",
            "nobind",
            "persist-key",
            "persist-tun",
            "",
            "# Authentication",
            "remote-cert-tls server",
            "auth SHA256",
            "cipher AES-256-GCM",
            "auth-user-pass",
            "auth-nocache",
            # Disable time-based TLS renegotiation on the CLIENT. The server can't push
            # reneg-sec (OpenVPN 2.4 rejects 'reneg-sec' in PUSH-OPTIONS), so without
            # this the client renegotiates after 1h and, with username/password auth,
            # re-prompts for credentials and drops the tunnel.
            "reneg-sec 0",
            "",
        ]

        # Add DNS servers (mode-aware; see _client_dns_directives)
        dns_lines = self._client_dns_directives(server_config)
        if dns_lines:
            config_lines.append("# DNS Configuration")
            config_lines.extend(dns_lines)
            config_lines.append("")

        # Add routes
        if push_routes:
            config_lines.append("# Routes")
            for route in push_routes:
                # Convert CIDR to network/mask format for OpenVPN
                try:
                    import ipaddress
                    network = ipaddress.ip_network(route, strict=False)
                    config_lines.append(f"route {network.network_address} {network.netmask}")
                except ValueError:
                    pass
            config_lines.append("")

        if compression:
            config_lines.append("compress lz4-v2")

        config_lines.extend([
            "",
            "# Verbosity",
            "verb 3",
            "mute 20",
            "",
        ])

        # Add inline certificates
        config_lines.extend([
            "<ca>",
            profile.ca_cert.strip(),
            "</ca>",
            "",
            "<cert>",
            profile.client_cert.strip(),
            "</cert>",
            "",
            "<key>",
            profile.client_key.strip(),
            "</key>",
            "",
        ])

        if profile.ta_key:
            config_lines.extend([
                "<tls-auth>",
                profile.ta_key.strip(),
                "</tls-auth>",
                "key-direction 1",
                "",
            ])

        return "\n".join(config_lines)

    async def _allocate_ip(self) -> Optional[str]:
        """Allocate next available IP from pool"""
        # Check IP pool table for available IPs
        result = await self.db.execute(
            select(IPPool)
            .where(IPPool.is_allocated == False)
            .where(IPPool.is_reserved == False)
            .limit(1)
        )
        ip_entry = result.scalar_one_or_none()

        if ip_entry:
            # Mark IP as allocated
            ip_entry.is_allocated = True
            await self.db.commit()
            return str(ip_entry.ip_address)

        # No pool entries available, generate from network range
        return await self._allocate_ip_from_range()

    async def _allocate_ip_from_range(self) -> Optional[str]:
        """Allocate IP from configured network range"""
        import ipaddress

        # Use saved server config for network settings
        server_config = get_server_config()
        vpn_network = server_config.get("vpn_network", settings.OPENVPN_NETWORK)
        vpn_netmask = server_config.get("vpn_netmask", settings.OPENVPN_NETMASK)

        network = ipaddress.ip_network(
            f"{vpn_network}/{vpn_netmask}",
            strict=False
        )

        # Get all assigned IPs
        result = await self.db.execute(
            select(VPNProfile.assigned_ip)
            .where(VPNProfile.is_revoked == False)
        )
        assigned_ips = {str(row[0]) for row in result.fetchall()}

        # Skip network address, gateway (.1), and broadcast
        for host in list(network.hosts())[1:]:  # Skip .1 (gateway)
            ip_str = str(host)
            if ip_str not in assigned_ips:
                return ip_str

        return None

    async def change_vpn_network(self, new_network: str, new_netmask: str) -> Tuple[bool, Optional[str]]:
        """Change the VPN subnet: reassign every profile's IP, rewrite ccd, and
        restart OpenVPN so the new `server <net> <mask>` takes effect.

        DISRUPTIVE: drops all live sessions and changes every client's tunnel IP.
        Clients do NOT need a new .ovpn (the IP is server-pushed via ccd) but must
        reconnect.
        """
        import ipaddress

        try:
            net = ipaddress.ip_network(f"{new_network}/{new_netmask}", strict=False)
        except Exception as e:
            return False, f"Rede/máscara inválida: {e}"
        if net.version != 4:
            return False, "Apenas IPv4 é suportado"
        if net.num_addresses < 4:
            return False, "Subrede pequena demais"

        network_addr = str(net.network_address)

        # 1. Persist to the backend-managed config (source of truth for IP alloc).
        cfg = get_server_config()
        cfg["vpn_network"] = network_addr
        cfg["vpn_netmask"] = new_netmask
        if not save_server_config(cfg):
            return False, "Falha ao salvar a configuração"

        # 2. Write the network file the OpenVPN container's start.sh reads on boot
        #    (shared /etc/openvpn volume) so a restart applies the new subnet.
        try:
            net_env = Path(settings.OPENVPN_CONFIG_DIR) / "network.env"
            net_env.write_text(f"OPENVPN_NETWORK={network_addr}\nOPENVPN_NETMASK={new_netmask}\n")
        except Exception as e:
            return False, f"Falha ao escrever network.env: {e}"

        # 3. Old pool entries belong to the previous subnet — clear them.
        await self.db.execute(delete(IPPool))

        # 4. Reassign each profile a fresh IP in the new range and rewrite its ccd.
        hosts = list(net.hosts())[1:]  # skip the gateway (.1)
        result = await self.db.execute(
            select(VPNProfile, User.username)
            .join(User, User.id == VPNProfile.user_id)
            .where(VPNProfile.is_revoked == False)
            .order_by(VPNProfile.created_at.asc())
        )
        rows = result.all()
        if len(rows) > len(hosts):
            return False, f"A subrede comporta {len(hosts)} IPs, mas há {len(rows)} perfis"

        for (profile, username), host in zip(rows, hosts):
            profile.assigned_ip = str(host)
            await self._create_ccd_file(username, profile)
        await self.db.commit()

        # 5. Restart the container so start.sh regenerates server.conf + masquerade.
        ok, err = await self.restart_server()
        if not ok:
            return False, f"Rede salva, mas falha ao reiniciar o OpenVPN: {err}"
        return True, None

    async def _generate_certificates(self, common_name: str) -> dict:
        """
        Generate client certificates using EasyRSA.

        In production, this would call EasyRSA or a PKI service.
        For now, returns placeholder certificates for testing.
        """
        # Check if EasyRSA is available
        easyrsa_path = self.pki_dir / "easyrsa"

        if easyrsa_path.exists():
            return await self._generate_certs_easyrsa(common_name)
        else:
            # Return placeholder certificates for development
            return self._generate_placeholder_certs(common_name)

    async def _generate_certs_easyrsa(self, common_name: str) -> dict:
        """Generate certificates using EasyRSA"""
        try:
            easyrsa = str(self.pki_dir / "easyrsa")

            # Step 1: Generate client request (key + csr)
            result = subprocess.run(
                [easyrsa, "--batch", "gen-req", common_name, "nopass"],
                cwd=str(self.pki_dir),
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                raise Exception(f"EasyRSA gen-req failed: {result.stderr}")

            # Step 2: Sign the client request
            result = subprocess.run(
                [easyrsa, "--batch", "sign-req", "client", common_name],
                cwd=str(self.pki_dir),
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                raise Exception(f"EasyRSA sign-req failed: {result.stderr}")

            # Read generated certificates
            ca_cert = (self.pki_dir / "pki" / "ca.crt").read_text()
            client_cert = (self.pki_dir / "pki" / "issued" / f"{common_name}.crt").read_text()
            client_key = (self.pki_dir / "pki" / "private" / f"{common_name}.key").read_text()

            ta_key = None
            ta_path = self.config_dir / "ta.key"
            if ta_path.exists():
                ta_key = ta_path.read_text()

            return {
                "ca_cert": ca_cert,
                "client_cert": client_cert,
                "client_key": client_key,
                "ta_key": ta_key,
            }

        except subprocess.TimeoutExpired:
            raise Exception("Certificate generation timed out")
        except FileNotFoundError as e:
            raise Exception(f"Certificate file not found: {e}")

    def _generate_placeholder_certs(self, common_name: str) -> dict:
        """Generate placeholder certificates for development"""
        logger.warning("Using placeholder certificates - NOT FOR PRODUCTION")

        placeholder_cert = f"""-----BEGIN CERTIFICATE-----
MIIBkTCB+wIJAKHBfpn+Yi8xMA0GCSqGSIb3DQEBCwUAMBExDzANBgNVBAMMBnZw
bi1jYTAeFw0yNjAxMzAwMDAwMDBaFw0zNjAxMjcwMDAwMDBaMBQxEjAQBgNVBAMM
CXtjb21tb25fbmFtZX0wXDANBgkqhkiG9w0BAQEFAANLADBIAkEA0Z3VS5JJcds3
xKxzGq3C1k5zV1P3Q4nGLmLz8OkJdZwlVz5jGrYM9+nHKxnGCz6pqJqJmN8MtPvH
K8MH9qLiNwIDAQABo1AwTjAdBgNVHQ4EFgQUl1lKwGVwQrV3N8A3xZ3P+gqr0T0w
HwYDVR0jBBgwFoAUfLT3K4xLcxOxKuxPdqxByN3WgH4wDAYDVR0TBAUwAwEB/zAN
BgkqhkiG9w0BAQsFAANBAHolhVq0I7qYLnjPnfRpvKLyTr5O0wMI5L2qQxF3XsJv
xZ8xH+7nJdOvLmPgMN6MFprQeCVpYAC5yxI5AJlPq+c=
-----END CERTIFICATE-----""".replace("{common_name}", common_name)

        placeholder_key = """-----BEGIN PRIVATE KEY-----
MIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA0Z3VS5JJcds3xKxz
Gq3C1k5zV1P3Q4nGLmLz8OkJdZwlVz5jGrYM9+nHKxnGCz6pqJqJmN8MtPvHK8MH
9qLiNwIDAQABAkBxMq/vHLQlkDzX+YLsN5xzQklxT0DFzLnx2kcMz8VwqwEZf2bE
qHxDFxu8hQJ7L7x5yNqN0PkCvZvJmL8VhiYBAiEA7mEdVxN8cUZPq8YXHK5J6dxm
6q8HQvMkL7u3PzpKZzECIQDhd8K7xK8NQa6Y9CxPps3CQvPhqN0nqKL8wq8jnxmn
dwIgYaVowaFDpQYbH4Lpk0t5dVVT6zN7WqVxGqKh7w2KuxECIQCIxRLJwNvoLk7A
cJ7WgJiY2z9lMzW8xC8NyqH7xBc2HwIhAJHnIz3gGqvp/R+5LzjNvCqDLgMl7f6e
z9j8bGcXxEpv
-----END PRIVATE KEY-----"""

        placeholder_ca = """-----BEGIN CERTIFICATE-----
MIIBjTCB9wIJAKHBfpn+Yi8wMA0GCSqGSIb3DQEBCwUAMBExDzANBgNVBAMMBnZw
bi1jYTAeFw0yNjAxMzAwMDAwMDBaFw0zNjAxMjcwMDAwMDBaMBExDzANBgNVBAMM
BnZwbi1jYTBcMA0GCSqGSIb3DQEBAQUAA0sAMEgCQQDRndVLkklx2zfErHMarcLW
TnNXU/dDicYuYvPw6Ql1nCVXPmMatgz36ccrGcYLPqmomoZ4zwy0+8crwwf2ouI3
AgMBAAGjUDBOMB0GA1UdDgQWBBR8tPcrjEtzE7Eq7E92rEHI3daAfjAfBgNVHSME
GDAWgBR8tPcrjEtzE7Eq7E92rEHI3daAfjAMBgNVHRMEBTADAQH/MA0GCSqGSIb3
DQEBCwUAA0EAYMq+G1w/qjXjBVSU0C1z3GppTNelY6ifsZRqOLb8S9xbGJIlbhQK
G4AZmjLbG+8UYeKnGr4kMzYrq4rFjLVlzA==
-----END CERTIFICATE-----"""

        return {
            "ca_cert": placeholder_ca,
            "client_cert": placeholder_cert,
            "client_key": placeholder_key,
            "ta_key": None,
        }

    async def _revoke_certificate(self, common_name: str) -> bool:
        """Revoke a client certificate"""
        easyrsa_path = self.pki_dir / "easyrsa"

        if not easyrsa_path.exists():
            logger.warning("EasyRSA not available, skipping certificate revocation")
            return True

        try:
            result = subprocess.run(
                [
                    str(easyrsa_path),
                    "--batch",
                    "revoke",
                    common_name
                ],
                cwd=str(self.pki_dir),
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"Certificate revocation failed: {result.stderr}")
                return False

            # Regenerate CRL
            subprocess.run(
                [str(easyrsa_path), "--batch", "gen-crl"],
                cwd=str(self.pki_dir),
                capture_output=True,
                timeout=30
            )

            return True

        except Exception as e:
            logger.error(f"Certificate revocation error: {e}")
            return False

    async def _create_ccd_file(self, username: str, profile: VPNProfile):
        """Create client-config-dir file for user-specific settings"""
        try:
            self.ccd_dir.mkdir(parents=True, exist_ok=True)
            ccd_file = self.ccd_dir / username

            lines = [
                f"# CCD for {username}",
                f"ifconfig-push {profile.assigned_ip} {get_server_config().get('vpn_netmask', settings.OPENVPN_NETMASK)}",
            ]

            # Add push routes
            for route in (profile.push_routes or []):
                lines.append(f"push \"route {route}\"")

            # Add DNS servers
            for dns in (profile.push_dns_servers or []):
                lines.append(f"push \"dhcp-option DNS {dns}\"")

            # Add DNS domains
            for domain in (profile.push_dns_domains or []):
                lines.append(f"push \"dhcp-option DOMAIN {domain}\"")

            # Bandwidth limit (if using tc/wondershaper)
            if profile.max_bandwidth_mbps:
                lines.append(f"# max-bandwidth: {profile.max_bandwidth_mbps} Mbps")

            ccd_file.write_text("\n".join(lines))
            logger.debug(f"CCD file created for {username}")

        except Exception as e:
            logger.error(f"Failed to create CCD file: {e}")

    async def _remove_ccd_file(self, username: str):
        """Remove client-config-dir file"""
        try:
            ccd_file = self.ccd_dir / username
            if ccd_file.exists():
                ccd_file.unlink()
                logger.debug(f"CCD file removed for {username}")
        except Exception as e:
            logger.error(f"Failed to remove CCD file: {e}")

    async def _get_user_by_profile(self, profile: VPNProfile) -> Optional[User]:
        """Get user for a VPN profile"""
        result = await self.db.execute(
            select(User).where(User.id == profile.user_id)
        )
        return result.scalar_one_or_none()

    async def get_server_status(self) -> dict:
        """Get OpenVPN server status"""
        status = {
            "is_running": False,
            "uptime_seconds": None,
            "connected_clients": 0,
            "total_bytes_in": 0,
            "total_bytes_out": 0,
            "version": None,
        }

        try:
            # Check if OpenVPN container is running
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", "edgegate-openvpn"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                is_running = result.stdout.strip().lower() == "true"
                status["is_running"] = is_running

                # If container is running, check if process is running inside
                if is_running:
                    proc_check = subprocess.run(
                        ["docker", "exec", "edgegate-openvpn", "pgrep", "-x", "openvpn"],
                        capture_output=True,
                        timeout=5
                    )
                    status["is_running"] = proc_check.returncode == 0

                    # Read connected clients count from status file via docker exec
                    try:
                        status_result = subprocess.run(
                            ["docker", "exec", "edgegate-openvpn", "cat", "/etc/openvpn/logs/status.log"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if status_result.returncode == 0:
                            status["connected_clients"] = status_result.stdout.count("CLIENT_LIST")
                    except Exception as e:
                        logger.warning(f"Could not read status file: {e}")

        except Exception as e:
            logger.error(f"Failed to get server status: {e}")

        return status

    async def get_active_connections(self) -> List[dict]:
        """Get list of currently connected VPN clients"""
        connections = []

        try:
            # Read OpenVPN status file via docker exec
            result = subprocess.run(
                ["docker", "exec", "edgegate-openvpn", "cat", "/etc/openvpn/status.log"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.warning("Could not read OpenVPN status file")
                return connections

            content = result.stdout
            lines = content.split('\n')

            # Parse CLIENT_LIST entries
            # Format: CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,
            #         Bytes Received,Bytes Sent,Connected Since,Connected Since (time_t),Username,Client ID,Peer ID
            client_list_started = False
            routing_table = {}

            for line in lines:
                line = line.strip()

                if line.startswith('ROUTING TABLE'):
                    client_list_started = False
                    continue

                if line.startswith('Virtual Address,Common Name'):
                    # Parse routing table to get virtual IPs
                    continue

                # Parse routing table entries to get VPN IP assignments
                if ',' in line and not line.startswith('CLIENT_LIST') and not line.startswith('HEADER') and not line.startswith('Updated'):
                    parts = line.split(',')
                    if len(parts) >= 2 and parts[0] and '.' in parts[0]:
                        vpn_ip = parts[0]
                        common_name = parts[1] if len(parts) > 1 else ''
                        if common_name:
                            routing_table[common_name] = vpn_ip

                if line.startswith('CLIENT_LIST'):
                    parts = line.split(',')
                    if len(parts) >= 8:
                        common_name = parts[1]
                        real_address = parts[2]
                        bytes_received = int(parts[4]) if parts[4].isdigit() else 0
                        bytes_sent = int(parts[5]) if parts[5].isdigit() else 0
                        connected_since = parts[6]

                        # Get VPN IP from routing table
                        vpn_ip = routing_table.get(common_name, 'N/A')

                        # Calculate connection duration
                        try:
                            connected_time = datetime.strptime(connected_since, '%a %b %d %H:%M:%S %Y')
                            duration_seconds = int((datetime.now() - connected_time).total_seconds())
                        except:
                            duration_seconds = 0

                        connections.append({
                            'username': common_name,
                            'vpn_ip': vpn_ip,
                            'real_ip': real_address.split(':')[0] if ':' in real_address else real_address,
                            'bytes_received': bytes_received,
                            'bytes_sent': bytes_sent,
                            'connected_since': connected_since,
                            'duration_seconds': duration_seconds
                        })

        except Exception as e:
            logger.error(f"Failed to get active connections: {e}")

        return connections

    # Same charset the app enforces on username creation (schemas/user.py). This
    # is a hard security boundary: `username` is fed to the OpenVPN management
    # interface, so anything outside this allowlist is rejected before it can
    # reach a command.
    _USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

    async def disconnect_client(self, username: str) -> Tuple[bool, Optional[str]]:
        """Disconnect a specific VPN client by username"""
        if not self._USERNAME_RE.match(username or ""):
            return False, "Invalid username"
        try:
            # OpenVPN management interface: send "kill <cn>" over the management
            # socket. The command is passed via stdin (NOT interpolated into a
            # shell string), so even a validated username can never break out
            # into a shell command. No `bash -c`, no shell metacharacters.
            result = subprocess.run(
                ["docker", "exec", "-i", "edgegate-openvpn",
                 "nc", "-w", "2", "localhost", "7505"],
                input=f"kill {username}\n",
                capture_output=True,
                text=True,
                timeout=5
            )

            # If management interface is not available, try alternative method
            if result.returncode != 0:
                logger.warning(f"Management interface not available, trying alternative method to disconnect {username}")

                # Alternative: Send SIGUSR1 to OpenVPN to reload, which will disconnect all clients
                # This is not ideal as it disconnects everyone, but works as fallback
                # For now, we'll return an error asking admin to restart server instead
                return False, "Management interface not configured. Please restart the server to disconnect all clients."

            logger.info(f"Successfully disconnected client: {username}")
            return True, None

        except subprocess.TimeoutExpired:
            return False, "Disconnect command timed out"
        except Exception as e:
            logger.error(f"Failed to disconnect client {username}: {e}")
            return False, str(e)

    async def start_server(self) -> Tuple[bool, Optional[str]]:
        """
        Start OpenVPN server (via docker)

        Returns:
            (success, error_message)
        """
        try:
            # Check if already running
            status = await self.get_server_status()
            if status["is_running"]:
                return False, "Server is already running"

            # Start openvpn container directly via docker
            result = subprocess.run(
                ["docker", "start", "edgegate-openvpn"],
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                logger.info("OpenVPN server started successfully")
                return True, None
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Failed to start OpenVPN server: {error_msg}")
                return False, f"Failed to start server: {error_msg}"

        except subprocess.TimeoutExpired:
            return False, "Start command timed out"
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            return False, str(e)

    async def stop_server(self) -> Tuple[bool, Optional[str]]:
        """
        Stop OpenVPN server (via docker)

        Returns:
            (success, error_message)
        """
        try:
            # Check if running
            status = await self.get_server_status()
            if not status["is_running"]:
                return False, "Server is not running"

            # Stop openvpn container directly via docker
            result = subprocess.run(
                ["docker", "stop", "edgegate-openvpn"],
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                logger.info("OpenVPN server stopped successfully")
                return True, None
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Failed to stop OpenVPN server: {error_msg}")
                return False, f"Failed to stop server: {error_msg}"

        except subprocess.TimeoutExpired:
            return False, "Stop command timed out"
        except Exception as e:
            logger.error(f"Error stopping server: {e}")
            return False, str(e)

    async def restart_server(self) -> Tuple[bool, Optional[str]]:
        """
        Restart OpenVPN server (via docker)

        Returns:
            (success, error_message)
        """
        try:
            # Restart openvpn container directly via docker
            result = subprocess.run(
                ["docker", "restart", "edgegate-openvpn"],
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                logger.info("OpenVPN server restarted successfully")
                return True, None
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Failed to restart OpenVPN server: {error_msg}")
                return False, f"Failed to restart server: {error_msg}"

        except subprocess.TimeoutExpired:
            return False, "Restart command timed out"
        except Exception as e:
            logger.error(f"Error restarting server: {e}")
            return False, str(e)

    async def update_server_conf_redirect_gateway(self, enabled: bool) -> Tuple[bool, Optional[str]]:
        """
        Update redirect-gateway setting in OpenVPN server.conf

        Args:
            enabled: True to force all traffic through VPN, False for split tunnel

        Returns:
            (success, error_message)
        """
        try:
            redirect_line = 'push "redirect-gateway def1 bypass-dhcp"'

            # Read current server.conf from container
            result = subprocess.run(
                ["docker", "exec", "edgegate-openvpn", "cat", "/etc/openvpn/server.conf"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return False, "Failed to read server.conf"

            lines = result.stdout.split('\n')
            new_lines = []
            redirect_found = False

            for line in lines:
                if 'redirect-gateway' in line:
                    redirect_found = True
                    if enabled:
                        # Keep or add the redirect line (uncommented)
                        new_lines.append(redirect_line)
                    # If disabled, skip this line (remove it)
                else:
                    new_lines.append(line)

            # If redirect wasn't found and should be enabled, add it after DNS options
            if enabled and not redirect_found:
                final_lines = []
                added = False
                for line in new_lines:
                    final_lines.append(line)
                    if not added and 'dhcp-option DNS' in line:
                        final_lines.append(redirect_line)
                        added = True
                if not added:
                    # Add at the end of push section if DNS not found
                    final_lines.insert(20, redirect_line)
                new_lines = final_lines

            # Write updated config back
            new_config = '\n'.join(new_lines)
            write_result = subprocess.run(
                ["docker", "exec", "-i", "edgegate-openvpn", "tee", "/etc/openvpn/server.conf"],
                input=new_config,
                capture_output=True,
                text=True,
                timeout=10
            )

            if write_result.returncode != 0:
                return False, "Failed to write server.conf"

            logger.info(f"Updated redirect-gateway to: {enabled}")
            return True, None

        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"Error updating server.conf: {e}")
            return False, str(e)

    async def update_server_conf_dns(
        self,
        dns_servers: Optional[list] = None,
        redirect_gateway: bool = True,
        internal_dns_server: Optional[str] = None,
        split_dns_domains: Optional[list] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Rewrite the DNS-related push directives in server.conf (mirrors
        _client_dns_directives).

        The directives are kept inside a delimited "managed-dns" block so this method is
        idempotent and never clobbers unrelated config. Any legacy bare
        ``push "dhcp-option DNS|DOMAIN|DOMAIN-ROUTE"`` lines (e.g. generated by start.sh)
        are also absorbed into the block.

        Every configured resolver (internal DNS + ``dns_servers``) is pushed regardless
        of tunnel mode, so a DNS IP set here always works whether or not redirect-gateway
        is on. In split tunnel each resolver also gets a host route so the DNS query
        reaches it through the VPN (this is what prevents the classic "ping IP works, name
        resolution fails" — the old code instead dropped DNS in split tunnel). In full
        tunnel redirect-gateway already routes everything, so the host routes are omitted.

        The DNS search domain is always pushed when set. DOMAIN-ROUTE (split NRPT) is only
        emitted in split tunnel and only when a resolver exists.
        """
        MARK_BEGIN = "# >>> managed-dns (edgegate) >>>"
        MARK_END = "# <<< managed-dns (edgegate) <<<"
        dns_servers = [str(d).strip() for d in (dns_servers or []) if str(d).strip()]
        internal_dns_server = (internal_dns_server or "").strip()
        split_dns_domains = [str(d).strip().lstrip(".") for d in (split_dns_domains or []) if str(d).strip()]

        try:
            # Resolvers to push: internal DNS first, then dns_servers, de-duplicated.
            resolvers = []
            for ip in ([internal_dns_server] if internal_dns_server else []) + dns_servers:
                if ip and ip not in resolvers:
                    resolvers.append(ip)

            # Build the managed block for the current mode
            block = [MARK_BEGIN]
            for ip in resolvers:
                if not redirect_gateway:
                    block.append(f'push "route {ip} 255.255.255.255"')
                block.append(f'push "dhcp-option DNS {ip}"')

            if split_dns_domains:
                block.append(f'push "dhcp-option DOMAIN {split_dns_domains[0]}"')
                if resolvers and not redirect_gateway:
                    for d in split_dns_domains:
                        block.append(f'push "dhcp-option DOMAIN-ROUTE {d}"')
            block.append(MARK_END)

            # Read current server.conf from container
            result = subprocess.run(
                ["docker", "exec", "edgegate-openvpn", "cat", "/etc/openvpn/server.conf"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False, "Failed to read server.conf"

            # Strip any previous managed block and legacy bare DNS/domain push lines
            new_lines = []
            in_block = False
            anchor_idx = None
            for line in result.stdout.split("\n"):
                stripped = line.strip()
                if stripped == MARK_BEGIN:
                    in_block = True
                    continue
                if stripped == MARK_END:
                    in_block = False
                    continue
                if in_block:
                    continue
                if ("dhcp-option DNS" in line
                        or "dhcp-option DOMAIN-ROUTE" in line
                        or "dhcp-option DOMAIN" in line):
                    continue
                new_lines.append(line)
                if stripped.startswith("topology "):
                    anchor_idx = len(new_lines)

            # Insert the fresh block after `topology`, else after `server `, else append
            if anchor_idx is None:
                for i, line in enumerate(new_lines):
                    if line.strip().startswith("server "):
                        anchor_idx = i + 1
                        break
            if anchor_idx is None:
                anchor_idx = len(new_lines)
            new_lines[anchor_idx:anchor_idx] = block

            new_config = "\n".join(new_lines)
            write_result = subprocess.run(
                ["docker", "exec", "-i", "edgegate-openvpn", "tee", "/etc/openvpn/server.conf"],
                input=new_config,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if write_result.returncode != 0:
                return False, "Failed to write server.conf"

            logger.info(
                "Updated DNS push (redirect_gateway=%s, internal_dns=%s, domains=%s)",
                redirect_gateway, internal_dns_server or "-", split_dns_domains or "-",
            )
            return True, None

        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"Error updating DNS push in server.conf: {e}")
            return False, str(e)

    async def generate_generic_ovpn_config(self) -> str:
        """
        Generate a generic .ovpn configuration file for all users.

        This config does not contain user-specific certificates.
        Users authenticate only with username/password.
        """
        # Load server configuration
        server_config = get_server_config()
        server_host = server_config.get("server_host", settings.OPENVPN_HOST)
        server_port = server_config.get("server_port", settings.OPENVPN_PORT)
        protocol = server_config.get("protocol", "udp")
        dns_servers = server_config.get("dns_servers", [])
        push_routes = server_config.get("push_routes", [])
        compression = server_config.get("compression", False)

        # Build configuration
        config_lines = [
            "# OpenVPN Client Configuration",
            f"# Server: {server_host}:{server_port}",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            "",
            "client",
            "dev tun",
            f"proto {protocol}",
            f"remote {server_host} {server_port}",
            "resolv-retry infinite",
            "nobind",
            "persist-key",
            "persist-tun",
            "",
            "# Authentication (username/password only)",
            "auth-user-pass",
            "auth-nocache",
            # Disable time-based TLS renegotiation on the CLIENT. The server can't push
            # reneg-sec (OpenVPN 2.4 rejects 'reneg-sec' in PUSH-OPTIONS), so without
            # this the client renegotiates after 1h and, with username/password auth,
            # re-prompts for credentials and drops the tunnel.
            "reneg-sec 0",
            "",
            "# Security",
            "remote-cert-tls server",
            "auth SHA256",
            "cipher AES-256-GCM",
            "",
        ]

        # Add DNS servers (mode-aware; see _client_dns_directives)
        dns_lines = self._client_dns_directives(server_config)
        if dns_lines:
            config_lines.append("# DNS Configuration")
            config_lines.extend(dns_lines)
            config_lines.append("")

        # Add routes
        if push_routes:
            config_lines.append("# Routes")
            for route in push_routes:
                try:
                    import ipaddress
                    network = ipaddress.ip_network(route, strict=False)
                    config_lines.append(f"route {network.network_address} {network.netmask}")
                except ValueError:
                    pass
            config_lines.append("")

        if compression:
            config_lines.append("compress lz4-v2")

        config_lines.extend([
            "",
            "# Verbosity",
            "verb 3",
            "mute 20",
            "",
        ])

        # Read CA certificate from file
        ca_cert = None
        ta_key = None

        ca_path = self.config_dir / "ca.crt"
        ta_path = self.config_dir / "ta.key"

        if ca_path.exists():
            ca_cert = ca_path.read_text()
        else:
            # Try easy-rsa location
            ca_path_alt = self.pki_dir / "pki" / "ca.crt"
            if ca_path_alt.exists():
                ca_cert = ca_path_alt.read_text()

        if ta_path.exists():
            ta_key = ta_path.read_text()

        if ca_cert:
            config_lines.extend([
                "<ca>",
                ca_cert.strip(),
                "</ca>",
                "",
            ])
        else:
            logger.warning("CA certificate not found for generic config")

        if ta_key:
            config_lines.extend([
                "<tls-auth>",
                ta_key.strip(),
                "</tls-auth>",
                "key-direction 1",
                "",
            ])

        return "\n".join(config_lines)
