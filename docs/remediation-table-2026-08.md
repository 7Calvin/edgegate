# EdgeGate — Tabela de Correções de Segurança

**Data:** 2026-08-24 · **Deploy + revalidação:** 2026-08-25 · **Branch:** `security-on-v2.0.2`
**Referência:** [`security-review-2026-08.md`](security-review-2026-08.md) ·
**Patch:** `edgegate-security-v2.0.2.patch`

> **Estado no servidor de teste (homolog v2.0.2):** o patch runtime
> foi aplicado em `/opt/edgegate`, as imagens **backend/frontend/nat-agent foram
> rebuildadas**, o Traefik e os agents de host (ipsec/update) reiniciados. Não é mais
> live-patch efêmero — está **baked nas imagens (persistente)**. Todas as correções
> abaixo foram **revalidadas ao vivo em 2026-08-25** (coluna *Evidência no servidor*).

## Corrigidos

| # | Serviço / Componente | Achado | Correção aplicada | Evidência no servidor (v2.0.2) |
|---|---|---|---|---|
| **H1** | OpenVPN + Backend API | Command injection (RCE root no container OpenVPN) | Allowlist de `username` + `kill` via stdin no `nc` (sem `bash -c`) | ✅ payload → `HTTP 400 Invalid username`; nenhum `poc.txt` criado no OpenVPN |
| **H6** | Docker host | `docker.sock` 666 = root p/ qualquer usuário local | `chmod 660` + grupo docker | ✅ `seven` (sem grupo docker) → `docker ps` **DENIED**; socket `srw-rw----` |
| **C1** | Backend (boot) | Secret default assina JWT → forja de admin | `model_validator` recusa boot em prod com secret default | ✅ presente na imagem; boot OK com secrets aleatórios (bloquearia no default) |
| **H2** | Backend Auth + Redis | Sem rate-limit no login | Redis 8/usuário, 20/IP → `429` | ✅ brute-force: `401`×8 → **`429`** |
| **H3** | Auth (back+front) | Tokens no `localStorage` (roubo por XSS) | Refresh → cookie HttpOnly/Secure/SameSite; store sem `localStorage` | ✅ login: body `refresh_token:null` + `Set-Cookie …HttpOnly; SameSite=strict; Secure` |
| **M8** | Auth (Backend) + Redis | Logout não invalidava o JWT | `jti` + blacklist Redis no logout | ✅ token → `/logout` → **mesmo token = `401`** |
| **M1** | IPsec (swanctl) | `name`/`psk` sem charset → injeção | validators Create+Update | ✅ presente na imagem (mesmo mecanismo do H4, provado via API) |
| **H4** | Firewall (nftables) + OpenVPN (CCD) | `name`/`desc`/`push_dns_domains` → injeção de config | rejeita newline/controle; domínio allowlist; Update revalida | ✅ criar regra com `\n` no nome → **`HTTP 422` "must not contain newlines or control characters"** |
| **M4** | OpenVPN (cert) | Chave privada PEM hardcoded no código | Cert/chave gerados em runtime (`cryptography`) | ✅ presente na imagem (gera cert válido; sem PEM no repo) |
| **M5** | Agents NAT / IPsec / Update | Comparação de token com `==` (timing) | `hmac.compare_digest` | ✅ presente nos 3 (nat-agent container + ipsec/update host, reiniciados) |
| **M6** | Traefik | Dashboard/API `insecure: true` | `api.insecure=false` | ✅ `insecure: false` no traefik.yml (Traefik reiniciado) |
| **M7** | Frontend (nginx) | Sem HSTS/CSP | HSTS + CSP + Referrer-Policy | ✅ headers `Content-Security-Policy` + `Strict-Transport-Security` presentes no painel |
| **M9** | Backend (CORS) | `allow_methods/headers=["*"]` | Métodos/headers explícitos | ✅ presente na imagem (`X-Requested-With` no main.py) |
| **L3** | Backend (TrustedHost) | `allowed_hosts=["*"]` fixo | `ALLOWED_HOSTS` configurável | ✅ presente na imagem |
| **M10** | Backend (deps) | `python-multipart` dup + CVE-2024-24762 | dedup + bump | ✅ `pip show python-multipart` → **0.0.18** |
| **M2** | Backend (docs) | Swagger público sem auth | docs off em prod (sessão paralela) | ✅ já no v2.0.2 |

## Não aplicados no servidor (por escopo do ambiente)

| Achado | Serviço | Situação |
|---|---|---|
| **M3** 🟢 (Grafana `admin/admin`) — **rebaixado p/ Baixo/preventivo** | Grafana / compose | O Grafana **não existe em deploy real**: o `docker-compose.yml` gerado pelo `install.sh` **nem inclui** o serviço (só o compose do repo, sob profile opt-in `monitoring`). Confirmado no homolog: sem container, sem listener 3001/9090, sem `GRAFANA_ADMIN_PASSWORD` no `.env`. O `admin/admin` nunca esteve exposto. Fix (senha obrigatória) é só higiene no compose do repo. |
| **H6 scripts** (`install.sh`, `fix-*`) | Infra | O socket já está 660 no host; a fix nos scripts entra no próximo install/update a partir do patch. |
| **C2 / C3 / L2 / deps jose·aiohttp / CI** | vários | Adiados — arquitetural, migração ou rebuild/teste (ver `security-review-2026-08.md`). |

## Ambiente de teste

- **Homolog (v2.0.2)** — patch runtime aplicado em `/opt/edgegate`, imagens
  **rebuildadas** (backend/frontend/nat-agent), Traefik + agents host reiniciados.
  **Persistente** (sobrevive a restart/recreate). Todos os containers healthy.
- Rotacionar a senha default do admin do painel. Socket em `660` (H6; cai em reboot
  até o install/scripts corrigidos entrarem).
