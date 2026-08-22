# Contributing to EdgeGate

Thanks for your interest in contributing! EdgeGate is a self-hosted VPN/gateway
management appliance (OpenVPN + IPsec + firewall/NAT + a web panel).

## Ground rules

- By contributing, you agree that your contributions are licensed under the
  [Apache License 2.0](LICENSE), the same license as the project.
- Be respectful. Assume good faith.
- Keep secrets out of the repo: never commit a real `.env`, private keys,
  certificates, `.ovpn` profiles, customer domains, or production IPs. The
  `.gitignore` blocks the common cases — do not force-add ignored files.

## Development setup

Requirements: Docker + Docker Compose, and (for host-side agents) an Ubuntu
24.04 host. The stack builds locally from source — no external registry.

```bash
# from the app directory
cp .env.example .env        # then fill in the placeholder secrets
docker compose up -d --build
```

- Backend: FastAPI (Python 3.11), SQLAlchemy + asyncpg, Alembic. Tests: `pytest`.
- Frontend: React + TypeScript + Vite. Build: `npm run build` (runs `tsc`).
- End-to-end: `scripts/e2e.sh` / `scripts/smoke_test.py`.

## Line endings

Shell scripts and systemd units MUST stay LF (enforced via `.gitattributes`).
A CRLF shebang breaks execution inside containers
(`exec /app/scripts/start.sh: no such file or directory`). If you edit on
Windows, make sure your editor writes LF for `*.sh`, `*.service`, and `vpnctl`.

## Pull requests

1. Branch from `main`.
2. Keep changes focused; describe the motivation in the PR body.
3. Make sure `pytest` (backend) and `npm run build` (frontend) pass.
4. For changes that touch a running appliance (install/update/PKI/DB), describe
   how you verified it end-to-end.

## Reporting security issues

Please do not open public issues for security vulnerabilities. Contact the
maintainer privately first.
