# EdgeGate — Assessment de Segurança Manual

**Data:** 2026-07-18 · **Tipo:** revisão manual dirigida por código (fora de pipeline)
· **Escopo:** backend FastAPI, agents privilegiados (NAT/IPsec/Update), config
Docker, auth (JWT/MFA/LDAP), geração de config de firewall/VPN.

> ⚠️ As severidades assumem os **defaults do repo não sobrescritos**. O
> `install.sh` gera um compose de produção que pode injetar segredos/tokens
> aleatórios — confirme contra o deploy real (ver *Verificação*) antes de cravar
> a severidade de C1/C3/C4.

Este documento é o produto de uma rodada de teste **manual**. Não altera código;
a remediação é uma fase seguinte (ver *Roadmap*). Metodologia: 3 varreduras de
código em paralelo cobrindo (1) privilégio/agents/`docker.sock`, (2) auth/segredos,
(3) injeção/escrita de arquivos/LDAP.

## Achados

### 🔴 Críticos (assumindo defaults)
| # | Achado | Local |
|---|--------|-------|
| C1 | **Segredos default assinam os JWTs** — `JWT_SECRET_KEY="change-me-jwt-secret"` / compose `dev-jwt-secret-change-in-production`. Quem conhece o default forja token de admin (`is_admin` vai no claim). | `app/core/config.py:100`; `docker-compose.yml:67` |
| C2 | **`/var/run/docker.sock` montado no backend = root no host** (o `:ro` é ilusório: dá pra `docker run` privilegiado montando `/`). RCE na API → host inteiro. | `docker-compose.yml:95`,`:55` |
| C3 | **update-agent em `0.0.0.0:8102`** com token estático `changeme-update-token`; `/update` dispara `bash update.sh` host-level (git pull + rebuild) = RCE no host se o token vazar/for default. | `docker/update-agent/update-agent.service:18`; `docker/update-agent/app.py:30,48,167` |
| C4 | **nat-agent `privileged`+`network_mode:host` em `0.0.0.0:8100`**, token estático `changeme-nat-token`; reprograma NAT/iptables do host. | `docker-compose.yml:191,195`; `docker/nat-agent/app.py:24,313,403` |

### 🟠 Altos
| # | Achado | Local |
|---|--------|-------|
| H1 | **Command injection autenticado**: `username` (path param cru, sem validação) interpolado em `bash -c "echo 'kill {username}'\|nc..."` sob `docker exec edgegate-openvpn` (container tem `NET_ADMIN`). | `app/api/v1/routes/vpn.py:373-381`; `app/services/vpn_service.py:740-746` |
| H2 | **Sem rate limiting no `/auth/login`** — `RateLimiter` é placeholder (`pass`), endpoint não a usa; sem lockout. Brute force livre. | `app/dependencies/auth.py:188-205`; `routes/auth.py:36-41` |
| H3 | **Sem revogação de JWT no logout** (`# TODO blacklist`), refresh não rotaciona → token roubado vale até 7 dias. Redis não é usado para tokens. | `routes/auth.py:123-135`; `services/auth_service.py:246-270` |
| H4 | **Config injection pelos schemas de _update_ sem validadores**: `IPsecConnectionUpdate`, `FirewallRuleUpdate`, `NATRuleUpdate`, `VPNProfileUpdate` gravam config (ipsec.conf/secrets, nftables, CCD) sem revalidar; `name`/`psk`/`push_dns_domains` sem charset → injeção de diretivas via `\n`. | `app/schemas/{ipsec,firewall,vpn}.py`; `models/ipsec.py:125-201`; `services/firewall_service.py:330-383`; `services/vpn_service.py:551-578` |
| H5 | **`DEBUG` default `true`** no compose → desativa o TrustedHostMiddleware e vaza stack traces ao cliente. | `docker-compose.yml:68`; `app/main.py:50,149` |

### 🟡 Médios
| # | Achado | Local |
|---|--------|-------|
| M1 | **Política de senha definida mas não aplicada** — `validate_password_strength` nunca é chamada em create/change. | `app/core/security.py:34-60`; `services/auth_service.py:344-365` |
| M2 | **MFA "obrigatório" burlável antes do 1º setup** — `requires_mfa = mfa_required AND mfa_enabled`. | `app/models/user.py:137-141`; `config.py:248` |
| M3 | **Username AD contorna a allowlist de charset** — `LoginRequest` só valida tamanho; provisionamento JIT não reaplica `^[a-zA-Z0-9._-]+$`; o valor flui p/ path CCD, args easyrsa e o `bash -c` (H1). | `services/auth_service.py:151-175`; `schemas/auth.py:10-14` |
| M4 | **Comparação de token dos agents não constant-time** (`!=`/`==`; nenhum `hmac.compare_digest`). | `nat-agent/app.py:313`; `ipsec-agent/app.py:18`; `update-agent/app.py:48` |
| M5 | **Security headers ausentes** no backend (sem CSP/HSTS/X-Frame-Options/X-Content-Type-Options). | `app/main.py:57-64` |
| M6 | **CORS com `allow_methods=["*"]`/`allow_headers=["*"]`** + `allow_credentials=True` (origem não é `*`). | `app/main.py:41-47` |
| M7 | **`npm audit`: 22 vulns (13 high)** — rollup path traversal (build-time), react-router open redirect (runtime, moderate). | `frontend/` deps |

### 🟢 Baixos
| # | Achado | Local |
|---|--------|-------|
| L1 | LDAP: `user_attr`/`required_group_dn` (config de admin) entram no filtro sem `escape_filter_chars` (o `username` do login **é** escapado). Impacto: lógica de grupo, admin-controlado. | `services/ldap_service.py:183-185,276-279` |
| L2 | ipsec-agent `/config/read` devolve `/etc/ipsec.secrets` (PSKs) e `/config/write` grava arquivos root arbitrários — mitigado por bind em `127.0.0.1`. | `docker/ipsec-agent/app.py:123-176` |

### ✅ Já corretos (não são achados)
Authz server-side (`require_admin` em todas as rotas admin, 403 para não-admin) ·
`escape_filter_chars` no username LDAP · `quote()` na URL NTLM · `subprocess` em
forma de lista em ~todos os comandos (exceto H1) · Traefik config via
`yaml.dump`/`json.dumps` (sem template injection) · `acme.json` escrito via
`input=` (sem interpolação).

## Verificação (quando o Docker estiver no ar)

- **H1** (principal): stack de dev ou gate efêmero, e rodar
  `curl -sk -X POST "https://localhost/api/v1/vpn/server/connections/x';id;%23/disconnect" -H "Authorization: Bearer <admin>"`
  — inspecionar efeito no container `edgegate-openvpn`. Única prova dinâmica sem tooling.
- **C1**: `docker exec edgegate-backend python -c "from app.core.config import settings; print(settings.JWT_SECRET_KEY)"`; se sair o default, forjar JWT admin e bater em rota admin.
- **C3/C4**: de outra máquina, `curl http://<host>:8102/health` e `:8100/health` — confirmar exposição; testar token default em `/status`.
- **H2**: laço de `POST /auth/login` com senha errada — confirmar ausência de throttling/lockout.
- **H3/H4/M1/M2/M3**: confirmáveis por leitura de código (evidência = file:line acima).

## Roadmap de remediação (fase seguinte, por impacto ÷ esforço)

1. **H1** — trocar `bash -c` por forma de lista / validar `username` na rota.
2. **C1/C3/C4** — falhar o boot se segredos/tokens forem os defaults; firewall/loopback nos ports 8100/8102.
3. **H4/M1/M3** — validadores Pydantic nos schemas de update; chamar `validate_password_strength`; reaplicar allowlist de username no provisionamento AD.
4. **H2/H3** — rate limit no login (slowapi/Redis) + blacklist de JWT no logout (Redis + `jti`).
5. **C2** — repensar o `docker.sock` no backend (agent de escopo mínimo).
6. **M4/M5/M6/H5/L1** — `hmac.compare_digest` nos agents; middleware de security headers; apertar CORS/TrustedHost; `DEBUG=false` default; escapar campos LDAP admin.

**Corroboração automática (quando quiser tooling):** `bandit`/`semgrep` (H1 +
injeção), `gitleaks` (C1), `pip-audit`, `trivy` nas imagens — plugáveis no gate.
