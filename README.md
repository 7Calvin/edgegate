# EdgeGate

**EdgeGate** is a self-hosted VPN & gateway management appliance with a modern web panel.
It brings together **OpenVPN** (client-to-site), **IPsec** (site-to-site, StrongSwan),
**firewall / NAT / port-forwarding**, user management, and monitoring — the whole stack runs
as Docker Compose on a single Ubuntu host, with a one-line installer.

> Runtime container, database, and network names follow the `edgegate-*` / `/opt/edgegate` convention.

---

## Features

### Users & access
- **Human accounts** (optional MFA/TOTP) and **service accounts** (API keys).
- Creating a user automatically provisions their OpenVPN profile.
- Admin password reset, enable/disable, delete-with-confirmation, and self-lockout protection.
- **Trusted Hosts** — per-user source-IP/CIDR allowlist for admins & service accounts (FortiOS-style).

### OpenVPN (client-to-site)
- Automatic X.509 client certs via EasyRSA; per-user fixed IP.
- Self-service `.ovpn` download; certificate regeneration and revocation.
- Server config managed from the panel (host, port, protocol, DNS, routes).

### Firewall, NAT & port forwarding
- Quick rules (block client-to-client, allow internal) and custom rules with drag-to-reorder priority.
- Port-forwarding (DNAT) wizard with service presets; auto-creates the matching firewall rule.
- Rules applied to the host via a privileged **NAT agent** (iptables DNAT/MASQUERADE).

### IPsec site-to-site (StrongSwan / swanctl)
- Full CRUD of tunnels from the UI; IKEv1/IKEv2, PSK auth, DPD.
- **High availability / failover** across two peer IPs (swanctl multi-homing) with automatic DPD failover,
  manual switch/rollback, and an active-endpoint indicator.
- **Peer config export** for **FortiGate** (SD-WAN CLI) or generic (pfSense/Endian/…).
- Real-time IKE SA + Child SA status, per-tunnel logs, AWS IMDSv2 IP auto-detection.

### Monitoring & security
- Live connections dashboard, per-user traffic stats, connection history, forced disconnect.
- Prometheus + Grafana for metrics.
- JWT + refresh tokens, optional MFA, API keys, full audit log, TLS.

---

## Architecture

Homologated on **AWS EC2, Ubuntu 24.04 LTS**, single NIC in a public subnet, NAT to a private subnet.

```
                Internet
                   │  HTTPS :443 / OpenVPN :1194 udp / IPsec :500,4500 udp
                   ▼
        ┌──────────────────────────────┐
        │   EdgeGate host (Ubuntu 24.04)│
        │                              │
        │  Docker Compose:             │
        │   traefik  (:80/:443, TLS)   │
        │   frontend (React)           │
        │   backend  (FastAPI :8000)   │
        │   postgres / redis           │
        │   openvpn  (:1194/udp)       │
        │   nat-agent (:8100, host net)│
        │   prometheus / grafana       │
        │                              │
        │  Host systemd services:      │
        │   strongswan (:500/:4500 udp)│
        │   ipsec-agent (:8101)        │
        │   update-agent (:8102)       │
        │                              │
        │  iptables NAT ──► private subnet / RDS / internal hosts
        └──────────────────────────────┘

VPN clients (10.8.0.0/24) → OpenVPN → NAT → private subnet
```

### Services

| Component | Kind | Port |
|---|---|---|
| traefik | container (reverse proxy + TLS) | 80, 443 |
| frontend | container (React/nginx) | — |
| backend | container (FastAPI) | 8000 |
| postgres / redis | container | 5432 / 6379 |
| openvpn | container | 1194/udp |
| nat-agent | container (host network) | 8100 |
| prometheus / grafana | container | — |
| strongswan | host systemd (IPsec) | 500/udp, 4500/udp |
| ipsec-agent | host systemd | 8101 |
| update-agent | host systemd (self-update) | 8102 |

> Ports 8100–8102 are internal only — do not expose them publicly.

---

## Tech stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2 (async / asyncpg), Alembic, Pydantic v2, Redis, PyOTP.
- **Frontend:** React 18 + TypeScript, Vite, TailwindCSS, shadcn/ui, TanStack Query, Zustand.
- **Infra:** Docker Compose, Traefik, OpenVPN 2.6+, StrongSwan 5.9+, iptables, Let's Encrypt / self-signed.

---

## Installation

On a clean **Ubuntu 24.04** host.

### Guided (interactive) — recommended

Download then run so the whiptail wizard gets a real TTY (a bare `curl | bash` leaves stdin busy):

```bash
curl -fsSL https://raw.githubusercontent.com/7Calvin/edgegate/main/bootstrap.sh -o edgegate-install.sh
sudo bash edgegate-install.sh
```

### Unattended (one-liner)

Sensible defaults (local Postgres, generated admin password, self-signed TLS) — just give the domain:

```bash
curl -fsSL https://raw.githubusercontent.com/7Calvin/edgegate/main/bootstrap.sh \
  | sudo NONINTERACTIVE=1 DOMAIN=vpn.example.com bash
```

Unattended options (environment variables):

| Variable | Default | Description |
|---|---|---|
| `DOMAIN` | *(required)* | Panel domain/host |
| `DB_TYPE` | `local` | `local` (Postgres in compose) or `external` |
| `ADMIN_PASSWORD` | *(generated)* | Set to choose the initial admin password |
| `VPN_NETWORK` / `VPN_PORT` | `10.8.0.0` / `1194` | OpenVPN network / port |
| `NAT_GATEWAY_NETWORK` | *(empty)* | CIDR of a subnet that uses this host as NAT gateway |
| `USE_LETSENCRYPT` | `false` | `true` for Let's Encrypt (needs `ACME_EMAIL` + public 80/443) |
| `INSTALL_ACTION` | `upgrade` if installed | `fresh` reinstalls from scratch (**deletes volumes**) |
| `VPN_REPO_REF` | `main` | Pin a specific release, e.g. `v2.0.0` |

> The command runs a remote script as root. To audit first, download and read `bootstrap.sh`
> (the guided option does this for you). The bootstrap clones into `/opt/edgegate-src`, runs
> `install.sh`, then removes the temporary clone.

### Prerequisites

- Ubuntu 24.04 LTS; Docker + Docker Compose; Git.
- Public IP (Elastic IP recommended) and a domain pointing to it (for TLS).
- Security group / firewall inbound: `80/tcp`, `443/tcp`, `1194/udp`, and (for IPsec) `500,4500/udp`.
- **On AWS: disable the instance Source/Dest Check** (required for NAT) and add a route to the VPN
  network in the private subnet's route table.

### Quick start (development)

```bash
git clone https://github.com/7Calvin/edgegate.git
cd edgegate
cp .env.example .env      # fill in the placeholder secrets
docker compose up -d
docker compose logs -f backend
```

Key environment variables live in `.env` (see `.env.example`): `INITIAL_ADMIN_*`, `POSTGRES_*`,
`JWT_SECRET_KEY` / `SECRET_KEY`, `OPENVPN_*`. Never commit a real `.env`.

---

## Operations (`vpnctl`)

```bash
vpnctl status                 # service status
vpnctl logs -f backend        # follow logs
vpnctl update                 # update to the latest release (health-gated, auto-rollback)
vpnctl backup                 # create a full backup (DB + OpenVPN PKI + config)
vpnctl restore <file.tar.gz>  # restore a backup (name-agnostic)
vpnctl reset-admin            # reset the admin password
vpnctl trusted-hosts clear <user>   # recover from a Trusted-Hosts self-lockout
```

### Backup & migration

`vpnctl backup` produces a single portable `.tar.gz` containing the Postgres dump
(`pg_dump --no-owner --no-acl`), the OpenVPN PKI/certs/ccd tarred from the volume, and the config.
Because it is **name-agnostic**, you can restore it onto a fresh install with different DB/container
names. Preserving the CA means existing `.ovpn` client profiles keep working after a restore — so the
supported migration path is: `vpnctl backup` → fresh install → `vpnctl restore`.

### Updates & releases

Each host runs an **update-agent** that pulls the latest git tag and rebuilds locally (build-before-switch,
health-gated, automatic rollback; the OpenVPN PKI is never touched). Publishing a new version = cutting a
tag with `scripts/release.sh` (or `release.ps1`) and clicking **update** in **Settings → System**.

The full REST API is documented at `/docs` (Swagger) and `/redoc`.

---

## Security

- Never commit `.env`, private keys, certificates, or `.ovpn` profiles (the `.gitignore` blocks the
  common cases).
- Use strong passwords (≥12 chars), enable MFA for admins, and use Trusted Hosts for internet-facing panels.
- Back up the CA regularly and rotate API keys / agent tokens periodically.
- Report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Shell scripts and systemd units must
stay LF (enforced by `.gitattributes`); a CRLF shebang breaks execution inside containers.

## License

Licensed under the **Apache License 2.0** — see [LICENSE](LICENSE) and [NOTICE](NOTICE). You may use, modify,
and fork EdgeGate, including commercially, provided you retain the attribution notices.
