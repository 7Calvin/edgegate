# EdgeGate — Revisão de Segurança Consolidada

**Data:** 2026-08-24 · **Versão auditada:** `v2.0.1` · **Tipo:** revisão de código
(read-only), fora de pipeline · **Escopo:** backend FastAPI, agents privilegiados
(NAT/IPsec/Update), config Docker/compose, auth (JWT/MFA/LDAP), geração de config
de firewall/VPN, frontend, secrets/CI.

> Este documento **consolida e verifica contra o código atual (`v2.0.1`)** os dois
> assessments anteriores — `SECURITY_AUDIT.md` (2026-02) e
> `security-assessment-2026-07.md` (2026-07), ambos **anteriores ao release público
> `v2.0.0`**. Passa a ser a **fonte de verdade**; os antigos ficam como histórico.
>
> **Nenhum código de produção foi alterado nesta rodada.** A remediação é uma fase
> seguinte — ver *Backlog priorizado*. Metodologia: 3 varreduras de código em
> paralelo (secrets/sensitive-files, backend/auth/injeção, infra/CI/frontend),
> corroboradas por leitura manual dos pontos críticos.

## Modelo de severidade

As severidades assumem os **defaults do repositório** — quem sobe o
`docker-compose.yml` commitado **direto**, sem passar pelo `install.sh`. O
`install.sh` gera segredos fortes (`openssl rand -hex 32`) e escreve um `.env` de
produção, então instalações via installer **não** estão expostas aos itens de
"secret default". O risco real é (a) o compose "as-is", (b) a **ausência de
fail-closed** no boot quando um segredo continua no default, e (c) itens que
independem do installer (injeção, headers, deps).

## Resumo executivo

| Severidade | Qtd | IDs |
|---|---|---|
| 🔴 Crítico | 3 | C1, C2, C3 |
| 🟠 Alto | 6 | H1–H6 |
| 🟡 Médio | 10 | M1–M10 |
| 🟢 Baixo/Higiene | 3 | L1, L2, L3 |

**Boa notícia primeiro:** nenhum segredo real está commitado (nem no histórico);
`.env.example` é 100% placeholder; `.gitignore` bloqueia `.env`/keys/certs (o antigo
VULN-010 está **corrigido**); authz server-side (`require_admin`) está presente em
todas as rotas admin; SQLAlchemy ORM (sem SQLi); bcrypt nas senhas; `subprocess` em
forma de lista em ~todos os comandos. O grosso do risco é **default inseguro +
ausência de fail-closed** e alguns pontos de **injeção autenticada**.

---

## 🔴 Críticos

### C1 — Segredos default assinam os JWTs → forja de token admin
**CWE-798 / CWE-306.** `backend/app/core/config.py:45,109`
(`SECRET_KEY="change-me-in-production"`, `JWT_SECRET_KEY="change-me-jwt-secret"`);
fallback público no `docker-compose.yml:66-67`
(`dev-secret-key-change-in-production` / `dev-jwt-secret-change-in-production`).
Tokens são HS256 (`app/core/security.py:85-90`) e `get_current_user` confia em
`sub`/`is_admin` do payload (`app/dependencies/auth.py:42-75`). **Não há checagem de
boot** rejeitando o default → quem conhece o default forja um `access` token de
admin e obtém controle total.
**Fix:** falhar o boot se `ENVIRONMENT=production` e qualquer segredo == default
conhecido (validator em `config.py`).

### C2 — Agents de host com token estático em `0.0.0.0`
**CWE-798 / CWE-306.** `docker/update-agent/app.py:30` (`0.0.0.0:8102`, roda `bash
update.sh` = git pull + rebuild como **root no host**),
`docker/nat-agent/app.py:24` (`privileged`+`network_mode:host`, `0.0.0.0:8100`,
reprograma iptables), `docker/ipsec-agent/app.py:24` (`127.0.0.1:8101`). Todos com
token default `changeme-*` (`docker-compose.yml:79-83`, `.env.example:101,107`) e
comparação por string simples. Token default alcançável pela rede = **RCE root no
host** (update/nat expostos em todas as interfaces).
**Fix:** bind em loopback/rede de controle privada + firewall nas portas 8100/8102;
exigir token gerado (fail-closed no default); `hmac.compare_digest`.

### C3 — Docker socket montado no backend internet-facing
**CWE-250.** `docker-compose.yml:92` monta `/var/run/docker.sock` no backend; o `:ro`
é ilusório (acesso de leitura ao socket já é root-equivalente — dá pra subir
container privilegiado montando `/`). `app/api/v1/routes/system.py:54-75,276-281`
usa `docker run`/`docker exec` livremente. Qualquer RCE no FastAPI (ver H1) →
**root no host**.
**Fix:** trocar o socket cru por um helper privilegiado de escopo mínimo
(allow-list de operações) ou um socket-proxy que filtra a API do Docker.

---

## 🟠 Altos

### H1 — Command injection (autenticado) no disconnect do OpenVPN
**CWE-78.** `app/services/vpn_service.py:806-812` monta `docker exec … bash -c "echo
'kill {username}' | nc localhost 7505"` interpolando `username`; a rota
`app/api/v1/routes/vpn.py:373-381` passa o path param **sem validação**. `x'; <cmd>;
echo '` escapa das aspas e executa comando arbitrário no container OpenVPN (que tem
`NET_ADMIN` + `/dev/net/tun`). Admin-autenticado, mas injeção clara.
**Fix:** validar `username` com `^[a-zA-Z0-9._-]+$` e usar a management socket API /
argv sem `bash -c`.

### H2 — Sem rate-limit/lockout no login
**CWE-799.** `app/dependencies/auth.py:200-217` — `RateLimiter.__call__` é `pass`
(stub "TODO"). `/login` não aplica throttle e `authenticate_user` não tem contador
de falhas/lockout (`app/services/auth_service.py:37-116`). Settings `RATE_LIMIT_*`
(`config.py:217-219`) não são usados. Brute force online livre.
**Fix:** implementar o rate limiter Redis + lockout/backoff por conta em `/login` e
`/auth/mfa/verify-login`.

### H3 — JWT (access+refresh) no `localStorage`
**CWE-922.** `frontend/src/stores/auth.ts:111-117` persiste os dois tokens via
`persist` do Zustand; `frontend/src/api/client.ts:16-18` os envia como `Bearer`.
Qualquer XSS rouba o refresh token de 7 dias.
**Fix:** refresh token em cookie `HttpOnly; Secure; SameSite=Strict`; access token
só em memória.

### H4 — Zero scanning de CI
**Supply-chain.** Não existe `.github/workflows/` (só `ISSUE_TEMPLATE/` e
`PULL_REQUEST_TEMPLATE.md`). Sem Dependabot, CodeQL/SAST, secret scanning,
pip-audit/npm audit ou Trivy — num projeto distribuído por `curl | bash`.
**Fix:** adicionar Dependabot + CodeQL + gitleaks + pip-audit/npm audit + Trivy nas
imagens. *(Fora do escopo desta branch — ver nota no fim.)*

### H5 — Defaults inseguros no `docker-compose.yml` shipado
**CWE-1188.** `docker-compose.yml:68-69` `DEBUG=${DEBUG:-true}` +
`ENVIRONMENT=development` (com `DEBUG=true`, `main.py:50` pula o
`TrustedHostMiddleware` e `main.py:149` vaza `str(exc)` ao cliente; uvicorn
`reload` ligado). `:20,38` publicam Postgres 5432 e Redis 6379 em `0.0.0.0` com
senha `changeme` (`:16,35`); `:115` expõe backend `8000` em HTTP puro (bypass do
TLS do Traefik). Admin inicial fraco: `config.py:256` `temp123$$` (8 chars, abaixo
da política de 12) / compose `Admin123!@#456`, sem troca forçada
(`init_db.py:66-96` só loga "troque a senha").
**Fix:** default `DEBUG=false`/`ENVIRONMENT=production`; não publicar DB/Redis/8000;
randomizar admin inicial + forçar troca no 1º login. *(O compose de produção gerado
pelo `install.sh:922` já faz bind do Postgres em `127.0.0.1` — o problema é o compose
do repo usado "as-is".)*

### H6 — `chmod 666 /var/run/docker.sock`
**CWE-732.** `install.sh:1298`, `scripts/fix-docker-socket.sh:35`,
`scripts/fix-permissions-production.sh:49` tornam o socket root-equivalente
escrevível por **qualquer** usuário/processo local.
**Fix:** adicionar o uid do backend ao grupo `docker` (o compose já tem
`group_add: ${DOCKER_GID}` em `:55-56`) em vez de afrouxar permissão do socket.

---

## 🟡 Médios

### M1 — Config injection swanctl via `name`/`psk` sem charset
**CWE-78/CWE-94.** `app/schemas/ipsec.py:21,40,127,143` — `name`/`psk` só têm limite
de tamanho (sem charset). São interpolados em `app/models/ipsec.py:286`
(`f"    {self.name} {{"`), `:353` (`secret = "{self.psk}"`) e `:201-203`
(ipsec.secrets); o ipsec-agent grava em `/etc/swanctl/conf.d/edgegate.conf` e dá
load. `}`/aspas/`\n` injetam diretivas swanctl arbitrárias. Admin-only, mas é um
primitivo de config-injection no host IPsec.
**Fix:** `name` → `^[A-Za-z0-9._-]+$`; rejeitar `"`/newline/control chars no `psk`.
(Mesmo padrão nos schemas de *update* de firewall/VPN.)

### M2 — Swagger `/docs` + `/openapi.json` públicos sem auth
**CWE-1004.** `app/main.py:32-34` (`docs_url="/docs"`); `docker-compose.yml:104`
roteia `PathPrefix('/docs') || PathPrefix('/openapi.json')` no Traefik sem
middleware de auth. Superfície da API enumerável publicamente.
**Fix:** desabilitar docs em produção ou gate atrás de auth.

### M3 — Grafana `admin/admin`  🟢 **(rebaixado p/ Baixo/preventivo)**
**CWE-798.** `docker-compose.yml:270` `GF_SECURITY_ADMIN_PASSWORD:-admin`;
espelhado em `.env.example:131-132`. Profile `monitoring`.
**Nota de severidade (2026-08-25):** o `docker-compose.yml` **gerado pelo `install.sh`
NÃO inclui o Grafana** — só o compose do repo o tem, sob profile opt-in `monitoring`
que ninguém ativa por padrão. Confirmado no homolog: **sem container, sem listener em
3001/9090, sem `GRAFANA_ADMIN_PASSWORD` no `.env`**. Ou seja o `admin/admin` **nunca
esteve exposto em deploy real** — é **preventivo, não vuln viva**.
**Fix (higiene):** senha obrigatória no compose do repo (feito). *(Novo — não estava
nos assessments anteriores.)*

### M4 — PEM private key de dev commitada em código de produção
**CWE-798.** `backend/app/services/vpn_service.py:548-557` embute um bloco
`-----BEGIN PRIVATE KEY----- … -----END PRIVATE KEY-----` (placeholder de dev, com
`logger.warning("NOT FOR PRODUCTION")`). Risco real baixo, mas é chave privada na
árvore → trip em secret scanner e mau precedente.
**Fix:** gerar cert placeholder em runtime ou mover para fixture de teste marcada.
*(Novo.)*

### M5 — Comparação de token dos agents não constant-time
**CWE-208.** `docker/nat-agent/app.py:397`, `docker/ipsec-agent/app.py:31`,
`docker/update-agent/app.py:52` usam `==`/`!=`. Side-channel de timing no token.
**Fix:** `hmac.compare_digest`.

### M6 — Traefik dashboard `insecure: true`
**CWE-16.** `docker/traefik/traefik.yml:5-7` (`api.dashboard=true`,
`insecure=true`). Não publicado hoje nos composes (exposição interna), mas 1 port
mapping expõe todo o routing sem auth.
**Fix:** `insecure: false`; expor via router autenticado com TLS se necessário.

### M7 — Sem HSTS/CSP; middleware de headers não atrelado aos routers
**CWE-693.** `docker/traefik/dynamic/internal.yml:13-21` define `frameDeny`/`nosniff`/
XSS/referrer mas **sem** `Strict-Transport-Security` e **sem** `Content-Security-
Policy`; os routers por label (compose) não referenciam `security-headers@file`.
Também `frontend/nginx.conf:34-36` e `docker/nginx/conf.d/default.conf:29-32` sem
CSP/HSTS.
**Fix:** adicionar HSTS + CSP e atrelar o middleware via
`traefik.http.routers.*.middlewares`.

### M8 — CSRF ausente / logout não revoga JWT / refresh sem rotação
**CWE-352/CWE-613.** `app/api/v1/routes/auth.py:122-134` (`# TODO blacklist`);
refresh não rotaciona (`app/services/auth_service.py:249-273`). Token roubado vale
até expirar. Sem proteção CSRF no projeto.
**Fix:** blacklist de JWT no Redis (via `jti`) no logout; rotação de refresh;
`SameSite=Strict` (casado com H3).

### M9 — CORS credentialed com métodos/headers wildcard
**CWE-942.** `app/main.py:41-47` `allow_credentials=True` com `allow_methods=["*"]`/
`allow_headers=["*"]`. Origens hoje são allow-list de localhost (`config.py:62`) —
não explorável imediatamente, mas frágil a qualquer `CORS_ORIGINS` amplo.
**Fix:** restringir métodos/headers explicitamente; manter origins como allow-list.

### M10 — Deps datadas + `/tmp` previsível no installer
**CWE-1104/CWE-377.** `backend/requirements.txt`: `python-jose==3.3.0` (advisories de
algorithm-confusion/DoS), `python-multipart==0.0.6` (DoS, **duplicada** em `:4,20`),
`aiohttp==3.9.1`, `paramiko==3.4.0`; front `npm audit` reportava ~22 vulns (13 high;
rollup path traversal build-time, react-router open redirect). `install.sh:1465` usa
`/tmp/vpn-install-$$` (previsível → symlink race como root).
**Fix:** revisar/atualizar deps + de-duplicar `python-multipart`; `mktemp` no
installer.

---

## 🟢 Baixos / Higiene

### L1 — Arquivo `nul` na raiz vaza IP de produção + host key SSH
`nul` (untracked, **não vazou no GitHub** — nunca foi commitado) contém uma linha
`known_hosts` (`<IP-de-produção> ssh-ed25519 AAAA…`) — host key **pública** (não é
segredo), mas expõe um IP de deploy. Artefato de `> nul`/`ssh-keyscan
… nul` em Git-Bash (no Windows `nul` é o dispositivo nulo; no Git-Bash vira arquivo).
**Fix:** deletar `nul`; ignorar nomes reservados do Windows no `.gitignore`.
*(Resolvido nesta branch.)*

### L2 — API keys / backup codes MFA em SHA-256 sem salt
**CWE-916.** `app/core/security.py:206-230` — SHA-256 sem salt; backup codes só 48
bits (`token_hex(6)`). Senhas usam bcrypt (**correto**).
**Fix:** HMAC-SHA256 com chave do servidor ou hash lento; aumentar entropia dos
backup codes.

### L3 — `TrustedHostMiddleware(allowed_hosts=["*"])`
**CWE-346.** `app/main.py:53` não valida Host.
**Fix:** allow-list de hosts via env.

---

## ✅ Já corretos (não são achados)

Authz server-side (`require_admin` em toda rota admin; 403 p/ não-admin — **nenhuma
rota privilegiada sem dependency de auth**) · SQLAlchemy ORM / queries
parametrizadas (sem SQLi) · bcrypt nas senhas · MFA TOTP + backup codes ·
`escape_filter_chars` no username LDAP + `quote()` na URL NTLM · `subprocess` em
forma de lista em ~todos os comandos (exceto H1) · nat-agent valida IPs com
`ipaddress` antes do `iptables` · Traefik/acme config via `yaml.dump`/`json.dumps`/
`input=` (sem template injection) · Trusted-Hosts (allow-list de IP de origem)
aplicado por request · `.gitignore` forte (bloqueia `.env`/keys/certs — VULN-010
antigo **corrigido**) · `.env.example` 100% placeholder · nenhum segredo real no
histórico git · lockfiles (`package-lock.json`) presentes.

---

## Status de remediação (2026-08-24, branch `security/review-and-guardian`)

Corrigidos e commitados nesta branch (a maioria deploy-validada no homolog v2.0.1):

| Achado | Fix | Validação dinâmica |
|---|---|---|
| **H1** | allowlist de `username` + `nc` via stdin (sem `bash -c`) | ✅ payload → `Invalid username`, sem RCE |
| **H6** | `docker.sock` 660 (não 666) nos scripts | ✅ user sem grupo docker perde root; backend ok |
| **C1** | validator fail-closed: recusa boot em prod com secret default | ✅ prod+default bloqueia; homolog passa |
| **H2** | rate-limit de login com Redis (`rate_limit.py`/`redis_client.py`) | ✅ 401×8 → 429 |
| **H3** | refresh token → cookie HttpOnly/Secure/SameSite; store sem localStorage | ✅ body `refresh_token:null`, refresh só por cookie |
| **M8** | jti + blacklist Redis no logout | ✅ token 401 após logout |
| **M1 / H4** | validators `name`/`psk` ipsec, firewall `name`/`desc`, VPN `push_dns_domains` (+ gaps Update) | ✅ injeção rejeitada |
| **M4** | cert placeholder gerado em runtime (remove PEM do repo) | ✅ cert válido gerado |
| **M5** | `hmac.compare_digest` nos 3 agents | syntax |
| **M6** | Traefik `api.insecure=false` | config |
| **M7** | HSTS + CSP + Referrer-Policy no nginx do frontend | ✅ headers presentes, painel carrega |
| **M9 / L3** | CORS restrito + `ALLOWED_HOSTS` configurável | smoke import |
| **M3** 🟢 | Grafana sem `admin/admin` (obrigatório) — **preventivo**: Grafana não entra no compose do install (sem container/porta no homolog) | YAML |
| **M10** | dedup de deps + bump `python-multipart` (CVE) | — |
| **M2** | Swagger fechado em prod (sessão paralela) | ✅ |

**Adiado (fora desta rodada — precisa design ou ciclo de rebuild/teste):**
- **C2 (bind dos agents em loopback):** os agents bindam `0.0.0.0` mas o `install.sh`
  já restringe via `ufw` às redes docker/VPN (verificado: portas filtradas de fora).
  Mudar o bind quebraria o path backend↔agent sem redesenho — mantido `hmac` (M5) +
  ufw; bind endurecido fica para uma fase de design.
- **C3 (docker.sock fora do backend):** requer socket-proxy de escopo mínimo —
  mudança arquitetural.
- **L2 (hashing de API keys/backup codes):** trocar o esquema invalida chaves/códigos
  já emitidos — precisa migração.
- **H5 (defaults do compose):** parcial — `DEBUG`/publicação de portas ainda a apertar
  no `docker-compose.yml` (C1 já cobre o secret default).
- **Deps datadas (`python-jose`, `aiohttp`):** bump / migração `jose`→`pyjwt` precisa
  rebuild + teste da imagem.
- **CI de segurança (Dependabot/CodeQL/gitleaks/pip-audit/Trivy):** fora do escopo
  escolhido; o pre-commit desta branch já cobre `gitleaks`+`bandit` localmente.

---

## Verificação sugerida (quando o Docker estiver no ar)

- **H1** (principal): stack de dev, `curl -sk -X POST
  "https://localhost/api/v1/vpn/server/connections/x';id;%23/disconnect" -H
  "Authorization: Bearer <admin>"` — inspecionar efeito no container
  `edgegate-openvpn`.
- **C1:** `docker exec edgegate-backend python -c "from app.core.config import
  settings; print(settings.JWT_SECRET_KEY)"`; se sair o default, forjar JWT admin.
- **C2:** de outra máquina, `curl http://<host>:8102/health` e `:8100/health`;
  testar token default em `/status`.
- **H2:** laço de `POST /auth/login` com senha errada — confirmar ausência de
  throttling/lockout.
- **H3/H5/M1/M4/L1:** confirmáveis por leitura de código (evidência = `file:line`
  acima).

**Corroboração automática (quando quiser tooling):** `bandit`/`semgrep` (H1, M1),
`gitleaks` (C1, M4), `pip-audit`/`npm audit` (M10), `trivy` nas imagens. O
pre-commit desta branch já pluga `gitleaks` + `bandit` localmente.

---

## Validação dinâmica — homolog (2026-08-24)

Teste ativo autorizado contra um appliance de homolog **instalado via `install.sh`**
(backend `v2.0.1`, `ENVIRONMENT=production`), a partir de uma conta SSH sem
privilégio de docker. **Lição central: as severidades "Crítico" acima assumem o
`docker-compose.yml` cru; o `install.sh` faz hardening que muda o quadro na
prática.** Nada foi deixado no host (artefatos de PoC removidos).

**🔴 Confirmados explorável ao vivo:**
- **H6 — host root por qualquer usuário local.** Socket em `srw-rw-rw-`
  (`chmod 666`). Usuário fora do grupo `docker` subiu container root
  (`docker run -v /:/host:ro`) e **leu `/etc/shadow`** (root-only). Confirma a
  escalada. *(Este é o achado de maior impacto real no box.)*
- **H1 — RCE root no container OpenVPN.** `POST
  /api/v1/vpn/server/connections/<payload>/disconnect` (admin) com `username =
  x'; id>poc.txt; echo '` executou `id` → `uid=0(root)` dentro do
  `edgegate-openvpn`. Injeção de shell via path param não-validado, provada.
- **M2 — Swagger público.** `/docs`, `/openapi.json`, `/redoc` → `HTTP 200` sem
  auth na internet; `/health` vaza `version`+`environment`.

**✅ Mitigados NESTE deploy (severidade real menor que a de "compose cru"):**
- **C1/H5:** segredos **aleatórios** (`openssl rand`), `production`, `DEBUG=False` —
  JWT não-forjável. Risco residual: ausência de fail-closed no boot.
- **C2:** agents bindam `0.0.0.0` (default ruim da app) **mas o `ufw` está ativo** e
  só libera `8100/8101/8102` para `172.17.0.0/16` + `172.20.0.0/16`; de fora, as três
  portas ficam **filtradas** (token do nat-agent também é aleatório). Risco residual:
  defesa-em-profundidade (quem estiver na rede docker/VPN alcança; depende do ufw).

**Observação:** ambas as contas admin (`calvin`, `admin`) estavam com `mfa_enabled =
False` apesar de `INITIAL_ADMIN_REQUIRE_MFA=true` — reforça o M2/L do assessment de
julho (MFA "obrigatório" não aplicado). A senha do admin `admin` foi redefinida para
teste do H1 (autorizado) — **deve ser rotacionada**.

**Prioridade de fix reordenada por explorabilidade real neste box:** H6 → H1 → M2 →
(C1/C2 residuais).

---

## Histórico

| Data | Ação |
|---|---|
| 2026-02-09 | Auditoria inicial (`SECURITY_AUDIT.md`, 18 vulns) |
| 2026-07-18 | Assessment manual (`security-assessment-2026-07.md`) |
| 2026-08-24 | **Consolidação verificada contra `v2.0.1`** (este doc) + agent guardião + pre-commit |
