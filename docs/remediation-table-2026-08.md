# EdgeGate — Tabela de Correções de Segurança

**Data:** 2026-08-24 · **Branch:** `security/review-and-guardian` · **Versão base:** v2.0.1
**Referência:** [`security-review-2026-08.md`](security-review-2026-08.md) ·
**Patch:** `edgegate-security-2026-08.patch` (30 arquivos)

A maioria das correções foi **deploy-validada** num appliance de homolog (backend
v2.0.1, HTTPS via Traefik) — a coluna *Evidência* traz a prova dinâmica quando houve.

## Corrigidos

| # | Serviço / Componente | Achado | Correção aplicada | Evidência | Commit |
|---|---|---|---|---|---|
| **H1** | OpenVPN + Backend API | Command injection (RCE root no container OpenVPN) via `username` do disconnect | Allowlist `^[a-zA-Z0-9._-]+$` + comando `kill` por **stdin** no `nc` (sem `bash -c`) | Payload de injeção → `HTTP 400 Invalid username`; **nenhum** `poc.txt` criado no container (antes: `id` rodava como uid=0) | `99b8124` |
| **H6** | Docker host / scripts de install | `docker.sock` em `666` = root no host p/ qualquer usuário local | `chmod 660` + grupo `docker` no `install.sh` e `scripts/fix-*` | `seven` (sem grupo docker) **perdeu** `docker ps` após 660; backend segue healthy (antes: lia `/etc/shadow` via container root) | `99b8124` |
| **C1** | Backend (config/boot) | Secrets default (`change-me`, JWT) assinam tokens → forja de admin | `model_validator` recusa boot em produção com secret/token default | Prod + `JWT_SECRET_KEY` default → boot **recusado**; homolog (secrets aleatórios) inicia normal | `590159f` |
| **H2** | Backend Auth + Redis | Sem rate-limit no login (`RateLimiter` era stub) → brute force livre | Contadores Redis por IP (20/15m) e usuário (8/15m) + `429`; fail-open se Redis cair | Brute-force real: `401`×8 → **`HTTP 429`** (retry_after 900); reset no sucesso | `fb3edf9` |
| **H3** | Auth (Backend + Frontend) | Access/refresh em `localStorage` → roubo por XSS | Refresh token vira cookie **HttpOnly/Secure/SameSite=Strict**; store sem `persist`, access só em memória | Login → `Set-Cookie refresh_token; HttpOnly; Secure` e body `refresh_token:null`; refresh só por cookie; sem cookie = `401` | `2121c07` |
| **M8** | Auth (Backend) + Redis | Logout não invalidava o JWT | `jti` no access token + blacklist Redis no logout + checagem no `get_current_user` | Token → `200`; após `/logout`, **mesmo token → `401`** | `fec6679` |
| **M1** | IPsec (StrongSwan) | `name`/`psk` sem charset → injeção de diretivas swanctl | Validators `name` (`^[A-Za-z0-9._-]+$`) e `psk` (sem aspas/newline/controle), Create + Update | No container: `name` com `}`/newline e `psk` com `"` **rejeitados**; válidos passam | `03d2cb5` |
| **H4** | Firewall (nftables) + OpenVPN (CCD) | `rule.name`/`description` e `push_dns_domains` sem validação → injeção de config | Rejeita newline/controle no firewall; domínio `^[A-Za-z0-9._-]+$` no VPN; Update revalida tudo | No container: `name` com newline e `push_dns_domains` com aspas/newline **rejeitados**; nome com espaço passa | `c834d3c` |
| **M4** | OpenVPN (geração de cert) | Chave privada PEM hardcoded no código (`vpn_service.py`) | Cert/chave self-signed gerados em **runtime** com `cryptography` | Container gera cert válido e parseável (CN correto); **sem PEM no repo** | `5360ad3` |
| **M5** | Agents NAT / IPsec / Update | Comparação de token com `==`/`!=` (timing side-channel) | `hmac.compare_digest` nos 3 agents | `py_compile` OK; `hmac.compare_digest` presente nos 3 | `4c880dc` |
| **M6** | Traefik | Dashboard/API `insecure: true` (sem auth em `:8080`) | `api.insecure=false` | Config (não reiniciei o Traefik do homolog — dashboard não é publicado) | `1dbbbb7` |
| **M7** | Frontend (nginx) | Sem HSTS nem CSP | HSTS + CSP + Referrer-Policy no `nginx.conf` (repetidos por-location p/ a pegadinha do nginx) | `nginx -t` OK; painel + bundle JS carregam (`200`); **CSP/HSTS presentes** no HTML | `1dbbbb7` |
| **M9** | Backend (CORS) | `allow_methods/headers=["*"]` com credenciais | Métodos/headers explícitos | Smoke-test de import OK | `62248d4` |
| **L3** | Backend (TrustedHost) | `allowed_hosts=["*"]` fixo | Setting `ALLOWED_HOSTS` configurável (default preserva comportamento) | Smoke-test de import OK; `allowed_hosts=['*']` no homolog | `62248d4` |
| **M3** | Grafana / Monitoring | `admin/admin` default no compose | `${GRAFANA_ADMIN_PASSWORD:?}` obrigatório; `.env.example` placeholder | `docker-compose.yml` YAML válido | `ecf7ab7` |
| **M10** | Backend (deps) | `python-multipart` duplicado + CVE-2024-24762 | De-dup (`multipart`/`email-validator`/`httpx`) + bump p/ `0.0.18` | `requirements.txt` sem duplicatas | `ea36c4e` |
| **M2** | Backend (docs) | Swagger `/docs` público sem auth | Docs desabilitados em prod + API reference autenticada (sessão paralela) | `/docs` → 200 removido em prod | `608b991` |

## Adiado (fora desta rodada)

| Achado | Serviço | Motivo de adiar |
|---|---|---|
| **C2** (bind dos agents) | Agents NAT/IPsec/Update | Bindam `0.0.0.0` mas `install.sh` já restringe via **ufw** às redes docker/VPN (verificado: portas filtradas de fora). Mudar o bind quebra o path backend↔agent — precisa design. |
| **C3** (docker.sock no backend) | Backend / Docker | Requer socket-proxy de escopo mínimo — mudança arquitetural. |
| **L2** (hashing API keys/backup codes) | Backend Auth | Trocar o esquema invalida chaves/códigos já emitidos — precisa migração. |
| **H5** (defaults do compose) | Infra / compose | Parcial: `DEBUG`/publicação de portas ainda a apertar (C1 já cobre o secret default). |
| Deps datadas (`python-jose`, `aiohttp`) | Backend | Bump / migração `jose`→`pyjwt` precisa rebuild + teste da imagem. |
| CI de segurança | CI/CD | Fora do escopo escolhido; pre-commit local (`gitleaks`+`bandit`) já cobre. |

## Notas do ambiente de teste (homolog)

- Rodou o código corrigido como **live-patch** (`docker cp` + restart) — efêmero,
  reverte num recreate de container. Persistência = mergear a branch + rebuild da imagem.
- Socket deixado em **660** (fix H6); senha do painel `admin` = `temp123$$` (rotacionar).
