# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

> Histórico anterior à v2.0.0 (série v1.x — OpenVPN, migração para swanctl/vici,
> IPsec HA/failover) está em [`docs/PROGRESS.md`](docs/PROGRESS.md).

## [Não lançado]

### Adicionado
- **IPsec route-based (interface XFRM) com failover determinístico** — novo modo de
  encaminhamento (`policy` | `route`, **`route` é o default** para novas conexões;
  as existentes seguem `policy`). Cada endpoint do peer vira uma conn própria
  (`<nome>-p` / `<nome>-b`) amarrada a um `if_id` e a uma interface `eg-<if_id>`; o
  primário/backup é escolhido por **métrica de rota**, e um hook `updown` gerencia a
  rota na subida/queda da SA. Resolve a oscilação em que os dois túneis do peer
  compartilhavam um único reqid/policy e o caminho ativo trocava a cada rekey.
  - Model: colunas `forwarding_mode` + `if_id_base`; `to_swanctl_routebased()`,
    `xfrm_ifaces()`; migration `017` (idempotente, `server_default='policy'`
    preserva as conexões existentes).
  - Service: `generate_swanctl_config` escolhe route/policy por conexão;
    `apply_config` reconcilia as interfaces XFRM via agent antes do reload;
    `_allocate_if_id_base()`; start/stop/status cientes das sub-conns `-p`/`-b`.
  - ipsec-agent: `POST /routebased/apply` (cria/limpa interfaces XFRM + updown +
    mapa de métricas) e `POST /routebased/active` (caminho ativo por métrica).
  - Frontend: seletor "Modo de encaminhamento" (route por padrão) nos formulários
    de criar/editar.

### Alterado
- **Export FortiGate: base de IDs do SD-WAN parametrizável (`sdwan_base`)** — deixa
  de usar IDs fixos (201/202) que sobrescreviam um SD-WAN existente; agora members =
  `base`/`base+1` e service = `base` (campo no modal de export). Também emite limiares
  de SLA realistas (loss/latency/jitter) e `link-cost-factor packet-loss`.

### Corrigido
- **DPD:** `dpd_action` agora emite o valor canônico do swanctl (`start`) em vez de
  `restart` (não-canônico; o 6.0.4 tolerava, mas outras versões poderiam ignorar e
  ficar sem failover).
- **Bytes 0 B** no detalhe da conexão e no dashboard de banda — o regex de parsing
  não casava a linha de SA route-based (anotação de `if_id`).
- Botão de refresh do status sem feedback visual (agora com spinner/disabled).

## [2.0.12] — 2026-09-14
### Corrigido
- **IPsec: auto-recuperação de túnel após queda de WAN** (`retry_initiate_interval`).
  Sem esse ajuste, quando uma queda de peer/WAN esgotava os retransmits afinados, o
  charon desistia ("establishing IKE_SA failed, peer not responding") e o túnel ficava
  caído até um initiate manual (observado num site single-link SC/Claro, ~50 min down).
  `install.sh` injeta os settings de retransmit/retry de forma idempotente (por setting)
  e adiciona `retry_initiate_interval=60`; `update.sh` faz self-heal em boxes existentes
  a cada update via `swanctl --reload-settings`.

## [2.0.11] — 2026-09-11
### Adicionado
- **Dashboard: throughput por protocolo com breakdown de IPsec por túnel.** Gráficos
  independentes de OpenVPN e IPsec com seletor de janela; amostragem de banda por
  túnel (migration `016` adiciona `tunnel_name` nullable a `bandwidth_samples`); o
  agregado filtra `tunnel_name IS NULL` para não duplicar. Linhas de referência de
  pico/média e readout de hover em slot fixo (sem "pular" o layout). Validado em
  gateway de dois túneis (soma por túnel = agregado, sem double-count).

## [2.0.10] — 2026-09-08
### Corrigido
- **nat-agent: cria automaticamente as regras FORWARD site-a-site dos túneis IPsec**
  (#4). Em hosts com política FORWARD restritiva (UFW `deny (routed)`), o tráfego entre
  a subnet local e a remota do túnel era descartado silenciosamente. `apply_ipsec_forwarding()`
  insere regras ACCEPT idempotentes (tag `vpn-ipsec-fwd`) no topo do FORWARD para
  `left_subnet <-> right_subnet` (ambos os sentidos), no startup, no `POST /apply` e no
  `POST /gateway/apply`.

## [2.0.9] — 2026-08-26
### Corrigido
- **Backup: migration `014` idempotente** para evitar crash-loop no boot. Guarda o
  `CREATE TABLE/INDEX` atrás de um check do inspector, para que `alembic upgrade head`
  tolere um DB onde `backup_schedules` já existe mas `alembic_version` ainda está < 014
  (box que rodou deploy manual/feature-branch antes da release). Sem o guard, dava
  `DuplicateTableError` e o backend reiniciava em loop.

## [2.0.8] — 2026-08-26
### Adicionado
- **Módulo de Backup Agendado (SFTP)**, no estilo FortiGate: um agendamento nomeado gera
  um backup completo (dump do Postgres + PKI do OpenVPN + manifest, `.tar.gz`) e envia por
  SFTP em horários HH:MM diários. Model `BackupSchedule` + migration `014`; `is_due()`
  tz-aware; upload via paramiko; placeholders `{hostname}/{name}/{date}/{time}/{datetime}`;
  CRUD `/backups` (admin) + `POST /{id}/run`; scheduler em background (advisory lock, tick
  30s) em `SCHEDULER_TIMEZONE`; auditoria do run manual e agendado; página "Backup" no painel.

## [2.0.7] — 2026-08-26
### Corrigido
- **Export FortiGate: PFS do phase2 espelha o ESP.** O gerador derivava o `dhgrp` do
  phase2 a partir do cipher do **IKE** (grupo 14), ignorando o ESP, e habilitava PFS grupo
  14 no phase2 do FortiGate mesmo quando o `esp_cipher` não tinha grupo DH — enquanto o
  swanctl rodava o CHILD_SA **sem PFS**. Resultado: o túnel subia mas o rekey do CHILD_SA
  morria com `NO_PROPOSAL_CHOSEN` a cada key-lifetime. Agora o PFS do phase2 espelha o
  `esp_cipher` (`set pfs enable`/`set dhgrp <grp>` quando há grupo DH, senão `disable`).

## [2.0.6] — 2026-08-26
### Corrigido
- **IPsec failover: fim do flap (`unique = no`).** Conexões com failover (backup peer /
  dois WANs) davam flap a cada ciclo de DPD (~10s): com o default `uniqueids=yes`, o
  INITIAL_CONTACT de cada túnel novo apagava o outro no responder. `to_swanctl()` passa a
  emitir `unique = no` apenas para conexões com `right_ip_backup`, deixando os dois paths
  coexistirem como SAs separadas. Validado ao vivo (2 IKE + 2 CHILD SAs estáveis 3+ min,
  zero INITIAL_CONTACT/delete).

## [2.0.5] — 2026-08-26
### Segurança
- **Remediação de segurança consolidada** (review + fixes, a maioria validada ao vivo em
  homolog). Detalhes em `docs/security-review-2026-08.md` e `docs/remediation-table-2026-08.md`.
  - 🔴 **H1** command injection → RCE root no container OpenVPN (validação de `username` +
    kill via stdin, sem `bash -c`).
  - 🔴 **H6** `docker.sock` 666 = root do host para qualquer usuário local (660 + grupo docker).
  - 🔴 **C1** secrets default assinando JWT (admin forjável) — validador fail-closed recusa
    subir em produção com secrets default.
  - 🟠 **H2** login sem rate-limit (brute force) → janelas por IP/usuário no Redis → 429.
  - 🟠 **H3** tokens no localStorage (roubo por XSS) → refresh token em cookie HttpOnly/Secure/SameSite.
  - 🟠 **M8** logout não revogava o JWT → `jti` + blacklist no Redis.
  - 🟠 **H4** injeção de config via nome/desc de regra de firewall + `push_dns_domains`.
  - 🟡 **M1** injeção de config no IPsec (name/psk) — validadores + escaping de PSK.
  - 🟡 **M4** chave PEM privada hardcoded no fonte → cert self-signed efêmero em runtime.
  - 🟡 **M5** comparação de token não constant-time → `hmac.compare_digest`.
  - 🟡 **M6** dashboard/API do Traefik inseguros (`api.insecure=false`).
  - 🟡 **M7** nginx do frontend sem HSTS/CSP → HSTS + CSP + Referrer-Policy.
  - 🟡 **M9** CORS wildcard de methods/headers → lista explícita.
  - 🟡 **M3** Grafana admin/admin default → senha obrigatória.
  - 🟡 **M10** `python-multipart` CVE-2024-24762 + deps duplicadas → dedupe + bump 0.0.18.
  - 🟢 **L3** `TrustedHost` `["*"]` → `ALLOWED_HOSTS` configurável.
### Adicionado
- Mensagens de erro amigáveis no frontend (`getApiErrorMessage`), agente de review
  `security-guardian` versionado e pre-commit local (gitleaks + bandit).
### Corrigido
- `install.sh` faz `chown` do bind mount `/app/data` para o uid do backend (corrige 500 ao
  salvar config do servidor); task de startup reaplica firewall VPN + NAT gateway do DB
  após recreate/update.

## [2.0.4] — 2026-08-25
### Corrigido
- **update-agent: self-heal da rota de progresso do update** + fallback no frontend. O
  frontend faz poll de `/update-agent/status` por uma rota dinâmica do traefik (não
  bind-mounted); se o volume a perde, o poll quebra silenciosamente (recebe o HTML do SPA
  em vez de JSON) e trava em "Reiniciando serviços…" para sempre. `update.sh` re-injeta a
  rota de forma idempotente a cada update; o card escala a mensagem após ~30s sem resposta.

## [2.0.3] — 2026-08-25
### Adicionado
- **MFA self-service:** o usuário remove o próprio MFA só com a senha da conta (TOTP
  opcional — recuperação de authenticator perdido), bloqueado quando `mfa_required`.
- **Admin reset de MFA:** `POST /users/{id}/mfa/reset` limpa o segredo TOTP + backup codes.
- **Entrada manual do segredo** no setup de MFA (alternativa ao QR).
- Aba "Monitoramento" na referência da API (filtra os 22 endpoints read-only) + gerador
  versionado (`scripts/gen-api-docs.py`).
### Corrigido
- Referência da API carregada via Blob URL / script externo para rodar sob CSP (o `srcDoc`
  grande era truncado, derrubando a busca e a aba Monitoramento).

## [2.0.2] — 2026-08-25
### Segurança
- **Docs interativos da API desabilitados por padrão em produção.** Swagger `/docs`, ReDoc
  `/redoc` e `/openapi.json` expunham toda a superfície da API e a versão exata **sem
  autenticação**. Agora atrás de `ENABLE_API_DOCS` (default false; DEBUG força on); quando
  desabilitados, retornam 404.
### Adicionado
- **Referência da API in-app autenticada** (substitui o Swagger público): página curada e
  self-contained servida só para admin autenticado, renderizada em iframe sandboxed com o
  tema do painel.

## [2.0.1] — 2026-08-24
### Adicionado
- **Backup completo pelo painel:** `GET /system/backup` (admin) faz dump do DB
  (`pg_dump --no-owner --no-acl`) + tar da PKI do OpenVPN, empacota `.tar.gz` restore-ready
  e faz stream do download; botão "Baixar backup".
- **Restore pelo painel** (upload + type-to-confirm): `restore.sh` no host + `POST /restore`
  (detached, destrutivo, recria a stack — espelha o `update.sh`).
### Corrigido
- **Let's Encrypt para o domínio do painel:** `install.sh` passa a emitir routers `Host(...)`
  seguros com `certresolver=letsencrypt` (antes só gerava routers de IP/self-signed, então o
  ACME nunca disparava); reemissão força `--force-recreate` do traefik.
### Alterado
- Scripts de release espelham a versão em `frontend/package.json` e `backend/app/__init__.py`
  (fonte única = `VERSION`); templates de issue/PR em `.github/`.

## [2.0.0] — 2026-08-22
- **Release público inicial do EdgeGate v2.0.0.**

[Não lançado]: https://github.com/7Calvin/edgegate/compare/v2.0.12...HEAD
[2.0.12]: https://github.com/7Calvin/edgegate/compare/v2.0.11...v2.0.12
[2.0.11]: https://github.com/7Calvin/edgegate/compare/v2.0.10...v2.0.11
[2.0.10]: https://github.com/7Calvin/edgegate/compare/v2.0.9...v2.0.10
[2.0.9]: https://github.com/7Calvin/edgegate/compare/v2.0.8...v2.0.9
[2.0.8]: https://github.com/7Calvin/edgegate/compare/v2.0.7...v2.0.8
[2.0.7]: https://github.com/7Calvin/edgegate/compare/v2.0.6...v2.0.7
[2.0.6]: https://github.com/7Calvin/edgegate/compare/v2.0.5...v2.0.6
[2.0.5]: https://github.com/7Calvin/edgegate/compare/v2.0.4...v2.0.5
[2.0.4]: https://github.com/7Calvin/edgegate/compare/v2.0.3...v2.0.4
[2.0.3]: https://github.com/7Calvin/edgegate/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/7Calvin/edgegate/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/7Calvin/edgegate/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/7Calvin/edgegate/releases/tag/v2.0.0
