"""
Application Settings and Configuration
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, field_validator, computed_field
from pydantic_core import MultiHostUrl


def _read_version() -> str:
    """Read the application version from the VERSION file.

    The file is the single source of truth for the running version. It is
    mounted into the container (``./VERSION`` -> ``/app/VERSION``) and rewritten
    by the update-agent after a successful update. Falls back to the ``VERSION``
    env var and finally to a hardcoded default when the file is absent.
    """
    for path in ("/app/VERSION", os.path.join(os.path.dirname(__file__), "..", "..", "..", "VERSION")):
        try:
            with open(path, "r") as f:
                value = f.read().strip()
                if value:
                    return value
        except OSError:
            continue
    return os.environ.get("VERSION", "1.0.0")


class Settings(BaseSettings):
    """Application configuration settings"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ==================== General ====================
    PROJECT_NAME: str = "EdgeGate"
    VERSION: str = _read_version()
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"

    # ==================== API ====================
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # Interactive API docs (Swagger /docs, ReDoc /redoc, /openapi.json). They expose the
    # full API surface and the exact running version WITHOUT authentication, so they are
    # OFF by default as a production hardening. Enable in dev with ENABLE_API_DOCS=true;
    # DEBUG also forces them on. When off, those paths return 404.
    ENABLE_API_DOCS: bool = False

    # ==================== Trusted Proxies / Client IP ====================
    # Number of reverse-proxy hops in front of the backend that we trust to
    # append X-Forwarded-For. On this stack that is Traefik alone (1). The real
    # client IP is read this many entries from the RIGHT of X-Forwarded-For;
    # anything the client injects on the left is ignored. This is the anti-spoof
    # basis for Trusted Hosts — set it to the actual number of trusted proxies
    # (0 disables XFF entirely and uses the raw socket peer).
    TRUSTED_PROXY_COUNT: int = 1

    # ==================== CORS ====================
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173"
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # ==================== Database ====================
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "edgegate"
    POSTGRES_USER: str = "edgegate_admin"
    POSTGRES_PASSWORD: str = "change-me"

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # ==================== Redis ====================
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    @computed_field
    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    CACHE_TTL_SHORT: int = 300  # 5 minutes
    CACHE_TTL_MEDIUM: int = 3600  # 1 hour
    CACHE_TTL_LONG: int = 86400  # 24 hours

    # ==================== JWT/Authentication ====================
    JWT_SECRET_KEY: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ==================== MFA/2FA ====================
    MFA_ISSUER_NAME: str = "EdgeGate"
    MFA_DIGITS: int = 6
    MFA_PERIOD: int = 30

    # ==================== Password ====================
    MIN_PASSWORD_LENGTH: int = 12
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_NUMBERS: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True

    # ==================== OpenVPN ====================
    OPENVPN_HOST: str = "vpn.example.com"
    OPENVPN_PORT: int = 1194
    OPENVPN_PROTOCOL: str = "udp"
    OPENVPN_NETWORK: str = "10.8.0.0"
    OPENVPN_NETMASK: str = "255.255.255.0"
    OPENVPN_DNS_1: str = "8.8.8.8"
    OPENVPN_DNS_2: str = "1.1.1.1"

    OPENVPN_CONFIG_DIR: str = "/etc/openvpn"
    OPENVPN_PKI_DIR: str = "/etc/openvpn/easy-rsa"
    OPENVPN_CCD_DIR: str = "/etc/openvpn/ccd"

    # EasyRSA
    EASYRSA_KEY_SIZE: int = 2048
    EASYRSA_CA_EXPIRE: int = 7500
    EASYRSA_CERT_EXPIRE: int = 3650
    EASYRSA_REQ_COUNTRY: str = "BR"
    EASYRSA_REQ_PROVINCE: str = "SP"
    EASYRSA_REQ_CITY: str = "SaoPaulo"
    EASYRSA_REQ_ORG: str = "Empresa LTDA"
    EASYRSA_REQ_EMAIL: str = "admin@empresa.com"
    EASYRSA_REQ_OU: str = "VPN Department"

    # ==================== Network ====================
    PUBLIC_INTERFACE: str = "eth0"
    NAT_GATEWAY_NETWORK: str = ""  # Private subnet behind this host (e.g. 10.48.0.0/16)

    # CIDR notation for VPN network (derived from netmask)
    @computed_field
    @property
    def OPENVPN_NETMASK_CIDR(self) -> int:
        """Convert netmask to CIDR notation"""
        netmask_to_cidr = {
            "255.255.255.0": 24,
            "255.255.255.128": 25,
            "255.255.255.192": 26,
            "255.255.255.224": 27,
            "255.255.255.240": 28,
            "255.255.0.0": 16,
            "255.0.0.0": 8,
        }
        return netmask_to_cidr.get(self.OPENVPN_NETMASK, 24)

    # ==================== Firewall ====================
    FIREWALL_ENGINE: str = "nftables"  # nftables or iptables
    FIREWALL_DEFAULT_POLICY: str = "drop"
    ENABLE_IP_FORWARDING: bool = True
    ENABLE_NAT: bool = True

    # ==================== NAT Agent ====================
    NAT_AGENT_URL: str = "http://127.0.0.1:8100"
    NAT_AGENT_TOKEN: str = "changeme-nat-token"

    # ==================== Update Agent ====================
    # Host-side systemd service that orchestrates full-system updates. It lives
    # OUTSIDE the docker-compose lifecycle so a rebuild/restart of the backend or
    # frontend cannot kill an in-flight update. The backend only proxies to it.
    UPDATE_AGENT_URL: str = "http://update-agent:8102"
    UPDATE_AGENT_TOKEN: str = "changeme-update-token"

    # ==================== Email ====================
    SMTP_ENABLED: bool = False
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True
    SMTP_FROM: Optional[str] = None

    # ==================== Logging ====================
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json or text
    LOG_FILE: str = "/var/log/edgegate/app.log"
    AUDIT_LOG_RETENTION_DAYS: int = 365

    # ==================== Metrics / Bandwidth Sampling ====================
    # Background sampler that snapshots server-wide OpenVPN byte counters to
    # power the dashboard throughput chart. Throughput = delta between samples.
    BANDWIDTH_SAMPLING_ENABLED: bool = True
    BANDWIDTH_SAMPLE_INTERVAL_SECONDS: int = 300  # sample every 5 min
    BANDWIDTH_RETENTION_HOURS: int = 48  # keep ~2 days of samples

    # ==================== IPsec Status Sync ====================
    # Background reconciler that refreshes each IPsec connection's persisted
    # status from the real StrongSwan state. Without it, a connection can stay
    # latched as "error" after a daemon restart even though the tunnel is up,
    # because status is otherwise only refreshed on a manual "Sync" click.
    IPSEC_STATUS_SYNC_ENABLED: bool = True
    IPSEC_STATUS_SYNC_INTERVAL_SECONDS: int = 20  # reconcile every 20s

    # ==================== Rate Limiting ====================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # ==================== Features ====================
    FEATURE_ALLOW_USER_REGISTRATION: bool = False
    FEATURE_ENABLE_2FA: bool = True
    FEATURE_ENABLE_API_KEYS: bool = True
    FEATURE_ENABLE_LDAP: bool = False

    # ==================== Quotas ====================
    MAX_USERS: int = 1000
    MAX_SERVICE_ACCOUNTS: int = 100
    MAX_CONCURRENT_CONNECTIONS_PER_USER: int = 5
    MAX_FIREWALL_RULES_PER_USER: int = 50
    MAX_BANDWIDTH_MBPS_DEFAULT: int = 100

    # ==================== Traefik Reverse Proxy ====================
    TRAEFIK_DYNAMIC_DIR: str = "/etc/traefik/dynamic"
    TRAEFIK_API_URL: str = "http://traefik:8080"
    TRAEFIK_ACME_EMAIL: str = ""  # Must be set to a valid email for ACME/Let's Encrypt
    TRAEFIK_ACME_STORAGE: str = "/acme/acme.json"

    # ==================== ACME DNS-01 ====================
    ACME_STAGING: bool = False  # Set True to use Let's Encrypt staging (for testing)
    ACME_CERTS_DIR: str = "/certs/manual"
    ACME_ACCOUNT_DIR: str = "/app/data/acme"

    @computed_field
    @property
    def ACME_DIRECTORY_URL(self) -> str:
        if self.ACME_STAGING:
            return "https://acme-staging-v02.api.letsencrypt.org/directory"
        return "https://acme-v02.api.letsencrypt.org/directory"

    # ==================== Admin ====================
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_EMAIL: str = "admin@empresa.com"
    INITIAL_ADMIN_PASSWORD: str = "temp123$$"
    INITIAL_ADMIN_REQUIRE_MFA: bool = True


# Singleton instance
settings = Settings()
