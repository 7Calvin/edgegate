# IPsec HA / Failover — Design & Migração para swanctl

> Documento de levantamento, decisões e plano da feature de **IPsec com alta disponibilidade / failover** para um cliente que conecta com **2 IPs fixos**, junto da **migração do strongSwan legacy (`ipsec.conf`) para swanctl/vici**.
>
> Ambiente de desenvolvimento/validação: **box de homolog** (o IP público muda entre reboots). **Sem releases durante o desenvolvimento** — trabalho direto no homolog; release só quando estiver validado.
>
> Última atualização: 2026-07-22.

> **STATUS: feature COMPLETA, testada ao vivo e versionada** na branch `feature/ipsec-failover` (commits `452b254` → `29fa919` → `eddee80`, no origin). O swanctl foi lançado em **v1.5.0–v1.5.2**; o failover + UI + export estão na branch aguardando merge/release (**~v1.6.0**). As seções **1–7** abaixo são o registro de design/migração (histórico). O estado final, os bugs corrigidos, o lado do FortiGate, o export e a validação estão nas seções **8–12**.

---

## 1. Objetivo

Um **cliente com 2 IPs públicos fixos** (dual-WAN/dual-ISP do lado dele) estabelece um túnel IPsec site-to-site com o nosso gateway, e o túnel deve ter **failover** entre os 2 IPs: se o caminho ativo cair, o túnel volta pelo outro IP.

## 2. Decisões (fechadas)

| Tema | Decisão | Porquê |
|---|---|---|
| Tipo | **Failover ativo/standby** (simples), não active/active | Cobre o ganho principal; active/active com IPsec exige ECMP/roteamento e é outro nível de esforço |
| Direção | **Simétrico** — nós também iniciamos/reconectamos pro IP de backup (não só responder) | Mais robusto; como o cliente tem IPs fixos, podemos iniciar também |
| Segurança | **IPs do cliente fixados no nosso lado** — **NÃO** usar `%any` | Reduz superfície de ataque; só os 2 IPs conhecidos podem negociar IKE |
| Subnets | **Mesmos subnets remotos nos 2 IPs** (mesmo site) | `rightsubnet` não muda → **o masquerade-exclude do nat-agent não precisa mudar** |
| Tempo de failover | **~dezenas de segundos** aceitável | Definido por `dpd_delay`/`dpd_timeout`; sub-segundo exigiria BFD/roteamento dinâmico (fora do escopo) |
| Stack | **Migrar para swanctl/vici** | Legacy `ipsec.conf` não faz múltiplos `right=` numa conn; swanctl `remote_addrs = IP1, IP2` faz nativo e seguro |

## 3. Arquitetura atual (o que vai ser modificado)

**strongSwan legacy stroke / `ipsec.conf`** — NÃO swanctl. O backend renderiza `/etc/ipsec.conf` + `/etc/ipsec.secrets` como texto e envia pro **ipsec-agent** (serviço systemd no host, porta 8101) que escreve os arquivos e roda o CLI `ipsec` (`ipsec reload`, `ipsec up/down`, `ipsec statusall`).

```
Frontend (IPsecPage.tsx)
  → FastAPI (api/v1/routes/ipsec.py)
    → IPsecService (services/ipsec_service.py)   — renderiza config em texto
      → ipsec-agent HTTP (docker/ipsec-agent/app.py, :8101) — escreve /etc/ipsec.{conf,secrets}, roda `ipsec ...`
  nat-agent (docker/nat-agent/app.py, :8100) — lê a tabela ipsec_connections direto do Postgres p/ excludes de masquerade
```

### 3.1 Modelo de dados — `backend/app/models/ipsec.py`
Tabela `ipsec_connections`. Enums: `IPsecStatus`, `IKEVersion` (ikev1/ikev2), `DPDAction` (restart/clear/hold/none).

Campos-chave (**modela exatamente UM peer** — um `right_ip`/`right_id`, sem backup/failover):
- Local (left): `left_ip`, `left_subnet` (CIDRs separados por vírgula), `left_id` (IP público ou FQDN)
- Remoto (right): `right_ip` (IP público do peer), `right_subnet`, `right_id`
- Auth: `auth_method` (psk/pubkey), `psk`
- IKE (fase 1): `ike_version`, `ike_cipher` (ex. `aes256-sha256-modp2048`), `ike_lifetime`
- ESP (fase 2): `esp_cipher`, `key_lifetime`
- Controle: `auto_start` (auto=start vs add), `dpd_action`
- Estado: `status`, `is_enabled`, `last_status_check`, `last_error`

Migration original: `backend/alembic/versions/20260318_005_add_ipsec_connections_table.py`.

### 3.2 Geração de config (hoje, legacy)
Métodos **no model** (não no service):
- `IPsecConnection.to_ipsec_conf()` (`models/ipsec.py:108`) → stanza `conn` legacy (`left=`/`right=`/`leftsubnet=`/`ike=`/`esp=`/`auto=`/`keyexchange=`). Um único `right=<right_ip>`. Multi-subnet usa o padrão `also=`/child-conns.
- `IPsecConnection.to_ipsec_secret()` (`models/ipsec.py:191`) → `left_id right_id : PSK "..."` (bidirecional).
- Service monta: `generate_ipsec_conf()`/`generate_ipsec_secrets()`/`apply_config()` (`services/ipsec_service.py:168-240`). Só renderiza conexões `is_enabled=True`.

### 3.3 ipsec-agent — `docker/ipsec-agent/app.py` (Flask, :8101, host)
Endpoints: `/health`, `/version`, `/status`, `/status/<name>`, `/up/<name>`, `/down/<name>`, `/reload` (roda `ipsec rereadsecrets` + `ipsec reload`), `/restart`, `/config/write`, `/config/read`, `/statusall`, `/logs`. Tudo via `run_ipsec_command()` → `subprocess ['ipsec', ...]`.
Parse de status: `_parse_status_output()` (`services/ipsec_service.py:464`) regex em `ipsec statusall` → deriva `tunnel_status` UP/IKE_ONLY/CONNECTING/DOWN.

### 3.4 Rotas — `backend/app/api/v1/routes/ipsec.py`
CRUD `/connections` (create/update/delete disparam `apply_config()` + refresh do gateway NAT), `/start`, `/stop`, `/restart`, `/status`, `/apply`, `/config/preview`, `/version`, `/statusall`, `/logs`, `/sync-status`, `/server-info`.

### 3.5 Acoplamento NAT — `docker/nat-agent/app.py`
`get_ipsec_excludes()` (`:169`) lê `SELECT right_subnet FROM ipsec_connections WHERE is_enabled=true` → esses CIDRs são excluídos do masquerade (`POSTROUTING ... RETURN` + `FORWARD ACCEPT`) pra o tráfego site-to-site manter o IP de origem real. **Como o failover mantém o mesmo `right_subnet`, isso NÃO muda.**

### 3.6 Frontend — `frontend/src/pages/IPsecPage.tsx`
`interface ConnectionForm` espelha o create schema. Forms de Adicionar/Editar, preview de config, status por conexão (cross-ref com status live: UP/IKE_ONLY/CONNECTING), ações start/stop/restart/logs.

## 4. Formato-alvo swanctl (VALIDADO)

Testado no homolog (carregou e listou com os 2 IPs). Formato do `/etc/swanctl/conf.d/<name>.conf`:

```
connections {
    <name> {
        version = 2
        local_addrs = <left_ip>
        remote_addrs = <right_ip>, <right_ip_backup>   # <-- failover nativo: 2 IPs fixos
                                                       #     (ordem invertida se prefer_backup)
        proposals = aes256-sha256-modp2048              # <- do ike_cipher
        rekey_time = <ike_lifetime>
        dpd_delay = 10s                                 # detecção rápida p/ failover
        local {
            auth = psk
            id = <left_id>
        }
        remote {
            auth = psk
            # SEM `id` pinado: com backup, o peer apresenta um IP-id diferente por caminho,
            # então aceitamos qualquer id aqui. Segurança = remote_addrs (IPs de origem) + PSK.
        }
        children {
            <name>-net {
                local_ts  = <left_subnet>
                remote_ts = <right_subnet>
                esp_proposals = aes256-sha256            # <- do esp_cipher
                dpd_action = restart                     # <- do dpd_action (failover)
                start_action = start                     # start ou trap
                rekey_time = <key_lifetime>
            }
        }
    }
}
secrets {
    ike-<name> {
        # TODOS os ids possíveis do peer, cada IP em DUAS formas: endereço e @string.
        id-1 = <left_id>          id-2 = @<left_id>
        id-3 = <right_id>         # se != dos IPs
        id-4 = <right_ip>         id-5 = @<right_ip>
        id-6 = <right_ip_backup>  id-7 = @<right_ip_backup>
        secret = "<psk>"
    }
}
```

Failover: `remote_addrs` com 2 IPs → charon tenta em ordem ao iniciar e aceita de qualquer um como responder; com `dpd_action=restart`, ao detectar peer morto ele re-inicia rotacionando pro próximo IP. Como os subnets são os mesmos, não há conflito de traffic selectors.

**⚠️ Duas correções essenciais (aprendidas ao vivo — ver §9):** (1) **NÃO pinar `id` no bloco `remote {}`** — com backup o peer autentica de IPs diferentes. (2) O **secret precisa listar todos os ids do peer, e cada IP em forma de endereço (`1.2.3.4`) E de string (`@1.2.3.4`)** — alguns peers (FortiGate com "Local ID" em texto) mandam um IP-id como **FQDN/KEY_ID (string)**, não como endereço IPv4; sem a forma `@` dá `no shared key found` e a auth falha.

## 5. Plano de migração / execução

### Marco 1 — swanctl mode no host ✅ (validado no homolog)
- `apt install strongswan-swanctl charon-systemd`.
- Trocar o daemon: `systemctl disable --now strongswan-starter` (legacy) → `systemctl enable --now strongswan` (swanctl/vici). São mutuamente exclusivos (2 charons conflitam nas portas 500/4500).
- Verificar: `/var/run/charon.vici` existe, `swanctl --stats` OK, charon carrega os plugins essenciais (aes/sha2/hmac/gcm/openssl/gmp/kernel-netlink/vici).
- **Reverter**: `systemctl disable --now strongswan; systemctl enable --now strongswan-starter`.
- Ruído: o CLI `swanctl` cospe `plugin 'X' failed to load` no stderr (plugins opcionais) — cosmético, o daemon está 100%. Usar `2>/dev/null` no agent.

### Marco 2 — formato de failover validado ✅
- `swanctl.conf` com `remote_addrs = IP1, IP2` carrega (`swanctl --load-all`) e lista os 2 IPs (`swanctl --list-conns`).

### Marco 2.5 — MIGRAÇÃO DE TÚNEL REAL validada ✅ (2026-07-21)
Um túnel legacy funcionando (`to-macro01`: nós `10.10.22.83`[id `107.20.115.56`] ↔ cliente `189.112.40.121`, `10.10.0.0/16 ↔ 192.168.128.0/23`, IKEv2 PSK `aes256-sha256-modp2048`) foi migrado pro swanctl: escrito o `connections{}`/`secrets{}` equivalente, trocado o daemon, e o **mesmo túnel re-estabeleceu com o peer real e tráfego fluindo** (ESP, bytes incrementando). Mapeamento model→swanctl confirmado: `ike_cipher`→`proposals`, `esp_cipher`→`esp_proposals`, `ike_lifetime`→`rekey_time` (conn), `key_lifetime`→`rekey_time` (child), `dpd_action`→child `dpd_action`, `left/right_id`→`local/remote id` (se `right_id` vazio, usar o `right_ip`), `auto_start`→`start_action`. **Config swanctl validado guardado em** `/etc/swanctl/conf.d/to-macro01.conf` no homolog.

### Marco 3 — código 🟡 (migração swanctl FEITA e validada; faltam polimentos)
Feito e **validado ao vivo** (backend rebuildado + agent redeployado no homolog, túnel real `to-macro01`):
1. ✅ **Gerador** — `IPsecConnection.to_swanctl()` / `.to_swanctl_secret()` (`backend/app/models/ipsec.py`). Mapeamento: `ike_cipher`→`proposals`, `esp_cipher`→`esp_proposals`, `ike_lifetime`→conn `rekey_time`, `key_lifetime`→child `rekey_time`, `dpd_action`→child `dpd_action` (hold→trap), `auto_start`→`start_action` (start/trap), `left/right_id`→`local/remote id` (right_id vazio ⇒ usa right_ip). `_remote_addrs()` já concatena o backup p/ failover (`getattr right_ip_backup`).
2. ✅ **Service** (`ipsec_service.py`): `generate_swanctl_config()`, `apply_config()` (escreve swanctl + `--load-all`), `_agent_write_config(swanctl_conf)`, e `_parse_status_output()` reescrito p/ `swanctl --list-sas` (blocos por IKE SA; captura `remote_host` = endpoint ativo p/ failover, bytes, TS, uptime, rekey).
3. ✅ **ipsec-agent** (`docker/ipsec-agent/app.py`): reescrito p/ swanctl (mesmos nomes de endpoint). `/config/write` é dono do conf.d (limpa outros `*.conf`, escreve `edgegate.conf`); `/reload`→`--load-all`; `/status`→`--list-sas`; `/up`→`--initiate --ike <n> --timeout 8` (evita travar o worker com peer inalcançável); `/down`→`--terminate --ike`.
4. ✅ **Routes** (`routes/ipsec.py`): DELETE agora chama `apply_config()` (reconcilia/descarrega do swanctl); UPDATE captura `name`/`is_enabled`/`status` ANTES dos awaits (evita `DetachedInstanceError` — async SQLAlchemy expira atributos pós-commit).

**Validado**: status(read), apply, create, edit, start/stop — todos OK em swanctl; `to-macro01` seguiu UP; CRUD end-to-end pelo backend confirmado.

**Auto-migração (para lançar como update atualizável) — FEITO ✅ (código, working tree):**
- ✅ **`update.sh` → `ensure_swanctl_mode()`**: roda após o sync e antes do build; idempotente (se já swanctl, só re-mascara o starter + refaz o agent). No host legacy: instala swanctl, para+**mascara** o `strongswan-starter`, mata o charon órfão, sobe o `strongswan.service`, verifica vici. Também um `_refresh_ipsec_agent()` (copia `docker/ipsec-agent/app.py`→`ipsec-agent/app.py` + restart — o sync não toca no run-dir do agent). Nunca fatal. Como o **backend regenera o config do banco**, os túneis migram sozinhos.
- ✅ **Rollback abaixo do swanctl = NEGADO**: `SWANCTL_FLOOR=1.5.0` no `update.sh`; se o alvo é anterior a 1.5.0 **e** o host está em swanctl, o update falha com mensagem clara (daemon não é auto-revertível; restaurar de backup / passos manuais). Decisão do usuário: tratar como negado.
- ✅ **`install.sh` (`install_strongswan`)**: instala `strongswan-swanctl`+`charon-systemd`, mascara o starter, usa `strongswan.service`, verifica vici. `ipsec-agent.service` agora depende de `strongswan.service`.

**Falta (polimento, não bloqueia o lançamento sem failover):**
- ⬜ **Config preview** (`/config/preview`, `/config/ipsec.conf`, `/config/ipsec.secrets`): ainda usam `generate_ipsec_conf()` (legacy) — trocar p/ `generate_swanctl_config()` (cosmético; toca schema+frontend).
- ⬜ **MSS clamp**: o `leftupdown=/etc/ipsec.d/mss-clamp.sh` legacy não foi portado pro `to_swanctl()` (child `updown`); avaliar (env vars do updown-plugin diferem do stroke).
- ⬜ **`swanctl --terminate` em conexão inativa** pode demorar; guard (só terminar se houver SA).

**Falta (para o FAILOVER, fase seguinte):**
- ⬜ **`right_ip_backup`** (nullable) no modelo + **migration** (o gerador já suporta via `getattr`) + campo no UI + indicador de endpoint ativo (`remote_host` do status). Teste ao vivo com o cliente nos 2 IPs.

**Para lançar o swanctl atualizável (sem failover):** commit + release **v1.5.0** (o piso do rollback). Ideal: testar o hop legacy→v1.5.0 num box legacy (ou aceitar a validação manual do homolog). Um box antigo que atualizar pra ≥1.5.0 auto-migra pro swanctl; rollback pra <1.5.0 é bloqueado.

### Gotchas descobertos na migração (2026-07-21)
- **Socket vici disputado**: legacy `/usr/lib/ipsec/charon` e `charon-systemd` compartilham `/var/run/charon.vici`; ao matar o legacy ele **remove o socket** que o charon-systemd usava → swanctl dá `Connection refused` **mesmo com o processo vivo** → `systemctl restart strongswan` recria. E `systemctl stop strongswan-starter` deixa o charon **órfão** segurando 500/4500 → `pkill -9 -f /usr/lib/ipsec/`.
- **`strongswan-starter` religa sozinho**: qualquer `ipsec` CLI (diagnósticos ou backend legacy) **auto-inicia** o starter → **mascarar** é obrigatório após migrar (`systemctl mask strongswan-starter`).
- **Pool do backend travava / login parava**: o agent hangando no `--initiate` (peer inalcançável, ex. conexão de teste com IP fake) segurava requests do backend → pool esgotado → login timeout. Resolvido com `--timeout 8` no initiate + restart do backend.

## 6. Plano de validação (com túnel real)

Estratégia decidida: **subir um túnel IPsec real funcionando por UM link** (funcionalidade legacy atual) e então **migrar esse túnel que funciona** pro swanctl — validação com tráfego real.

1. Criar a conexão pelo painel (legacy), túnel UP ("Túnel ATIVO").
2. Capturar o `ipsec.conf` legacy + a row do banco (estado que funciona).
3. Gerar o `swanctl.conf` equivalente a partir dos mesmos dados.
4. Trocar pro modo swanctl, carregar o config migrado, confirmar que o **mesmo túnel re-estabelece** (`swanctl --list-sas` com SA up).
5. Adicionar o **2º IP** (`remote_addrs`) e testar o failover **matando um caminho** (cliente real com os 2 IPs fixos).

## 7. Considerações operacionais / riscos

- **⚠️ GOTCHA CRÍTICO da troca de daemon (validado ao vivo)**: `systemctl stop strongswan-starter` **NÃO mata o charon legacy forkado** (`/usr/lib/ipsec/charon`) — ele fica **órfão segurando as portas UDP 500/4500**. Aí o `charon-systemd` (swanctl) sobe sem conseguir bindar → loga `no socket implementation registered, sending failed`, porta local `[0]`, 0 pacotes IKE saem, túnel preso em CONNECTING. **A migração TEM que forçar o kill do charon legacy** antes de subir o swanctl: `systemctl stop strongswan-starter; pkill -9 -f '/usr/lib/ipsec/(starter|charon)'; systemctl restart strongswan`. Diagnóstico: `ss -unlp 'sport = :500'` mostra quem segura a porta.
- **Troca de daemon é one-way-ish por box**: ao migrar pra swanctl, os recursos IPsec do painel param até o agent/backend serem atualizados (chamam o CLI `ipsec`, não swanctl). No homolog sem túnel real, sem impacto.
- **Prod com IPsec**: migrar exige o mesmo passo (install swanctl + troca de serviço + agent novo). Planejar janela. IPsec = charon no host (não é container).
- **`dpd_action` na saída do `--list-conns`** apareceu como "start" no teste — detalhe a confirmar no Marco 3 com o failover ao vivo.
- **nat-agent**: sem mudança (mesmo `right_subnet`). Confirmar que continua excluindo do masquerade após a migração.
- **install.sh**: hoje instala strongSwan legacy; precisa passar a instalar swanctl e habilitar `strongswan.service`.

## 8. Feature de failover — o que foi construído

Migração swanctl entregue em **v1.5.0** (código + auto-migração), **v1.5.1** (update.sh conserta o bind-mount do traefik que derruba no reboot), **v1.5.2** (backend aplica a config IPsec no startup — túneis auto-carregam após restart/migração). Prod (`alphaquimica`) migrada pra swanctl. O **failover** em si está na branch `feature/ipsec-failover` (não lançado ainda):

- **Campos**: `right_ip_backup` (2º IP do peer; migration `012`) e `prefer_backup` (migration `013`, `server_default=false`). `right_id` pode ser vazio (default = `right_ip`).
- **Geração**: `_remote_addrs()` monta `remote_addrs = primário, backup` (ordem invertida quando `prefer_backup`). `to_swanctl_secret()` emite todos os ids + cada IP em forma endereço e `@string` (ver §4/§9).
- **Botões de ops** (por conexão): **Testar failover** (bloqueia o caminho ativo e verifica a volta pelo backup; auto-restaura em 120s), **Switch manual** (força o backup: bloqueia o primário + restart), **Rollback** (volta pro primário + desbloqueia). Endpoints: `/connections/{id}/test-failover`, `/switch-backup`, `/rollback-primary`.
- **ipsec-agent**: `/block-peer`, `/unblock-peer`, `/test-failover-block` (INBOUND-only — ver §9), `/active-remote` (lê a política XFRM de saída = qual endpoint carrega tráfego; único sinal confiável com 2 SAs up).

## 9. Bugs encontrados e corrigidos (todos validados ao vivo)

| # | Sintoma | Causa | Fix |
|---|---|---|---|
| 1 | Auth falha pelo IP de backup (retransmit silencioso) | secret só listava o IP primário; `remote{}` pinava o id do primário | secret com todos os ids; sem pin de id no `remote{}` |
| 2 | `no shared key found` mesmo com o IP no secret | FortiGate manda "Local ID" em texto como **ID_FQDN (string)**, não IPv4-addr → tipo não bate | emitir cada IP em **duas formas**: `1.2.3.4` **e** `@1.2.3.4` |
| 3 | `PUT /connections` retorna 500 mas salva | serializava o objeto ORM após awaits que expiraram atributos → `DetachedInstanceError` | re-buscar (`get_connection_by_id`) antes de retornar |
| 4 | Edit apagava Peer ID / IP de backup | o form reenviava todos os campos, e um vazio sobrescrevia | edit **diff-based**: só envia o que mudou |
| 5 | Dashboard mostrava "2/3" com 1 conexão | contava **SAs** (failover = 2 SAs up; rekey = 3 transitório) | agrupar por nome de conexão → "1/1" + `active_paths` |
| 6 | `test-failover` não chaveava | agent bloqueava OUTPUT → o `sendmsg` do DPD dá **EPERM** (erro local), o charon só retransmite e nunca declara peer morto | bloquear **só INBOUND** (o probe sai e não recebe resposta) |
| 7 | Detecção de peer morto ~2min | `dpd_delay=30s` + retransmit padrão do charon | `dpd_delay=10s` + `retransmit_timeout=2.0/base=1.6/tries=4` no `strongswan.conf` (em `install.sh`) → ~30-42s |
| 8 | `test-failover` bloqueava o endpoint **ocioso** | com 2 SAs up, o ativo é o **último SA instalado** — nem `prefer_backup` nem `list-sas` refletem | novo `/active-remote` lê a política XFRM de saída |

## 10. Lado do cliente (FortiGate) — setup e gotchas

O cliente é um **FortiGate (FortiOS 7.4)** com 2 WANs, usando **SD-WAN** pra active/standby. Gotchas resolvidos (a config real do backup `MACPOAFW01` virou o template do export — §11):

- **NAT-T**: o FortiGate tinha `set nattraversal disable` no phase1 primário. Como **nós** estamos atrás de NAT, NAT-T é obrigatório → o INIT fechava mas o `IKE_AUTH` na 4500 não respondia. Fix: `set nattraversal enable` (é o default; só aparece quando desligado).
- **Source do Performance SLA**: o probe do SLA nascia da interface de túnel (`192.168.1.2`) / WAN — **fora** da subnet protegida `192.168.128.0/22` → nosso lado dropa na decriptação. Fix: `config system sdwan / config health-check / set source <IP do Forti dentro de 192.168.128.0/22>`.
- **NAT no tráfego transit**: hosts do cliente não alcançavam o `10.10.x` porque o tráfego saía pela **internet (ppp2) com SNAT** (rota em cache, não a policy de VPN). A rota já estava certa (`via sdwan-zone`); o conserto foi **`diagnose sys session clear`** (a sessão em cache estava grudada no caminho velho). A policy de VPN **não** aplica NAT (site-to-site preserva o IP real).
- **ECMP / roteamento**: rotas equal-cost pros 2 túneis causam **roteamento assimétrico**. Usar SD-WAN (zone + rule + SLA) + rota via `sdwan-zone` (+ rota blackhole distância 254 como safety), **sem** rotas equal-cost.
- **localid**: o FortiGate apresenta o IP da WAN como IKE id — cobrir no secret (§9 bug 2).
- **IPs mudam**: o homolog troca de IP público no reboot, e a WAN do cliente também mudou (`189.112.40.121` → `201.48.143.18`). Ajustar `left_id`/`right_ip` no painel + `remote-gw`/`localid` no FortiGate. (Opção FQDN/DDNS recusada — fica IP fixo, reajusta quando muda.)

## 11. Config view + export para o peer

- **Ver config gerada** (ícone 👁 por conexão) → `GET /connections/{id}/config`: mostra o `connections{}`/`secrets{}` swanctl que aquela conexão gera (PSK oculto).
- **Baixar config** (menu `⋮ → Baixar config`) → `GET /connections/{id}/export?target=fortigate|generic`:
  - **fortigate**: script de CLI pronto pra colar (address, phase1/phase2, SD-WAN zone/members/SLA/rule, rota+blackhole, policy), **com o PSK real** e todos os gotchas da §10 embutidos. Objetos com prefixo `EG_` (aditivo/idempotente) + bloco de UNDO. Campos do FortiGate (WAN pri/bak, interface LAN, source do SLA, versão FortiOS, Local IDs) vêm de um mini-form; preview ao vivo.
  - **generic**: folha de parâmetros device-agnóstica (nosso lado, lado do cliente, Fase 1/2, DPD) pra pfSense/Endian/Mikrotik/etc.
- **UI**: header enxuto (só "Adicionar Conexão"; "Aplicar" removido pois aplica automático; "Reiniciar StrongSwan" foi pra barra de status). Ações da linha colapsadas num **dropdown `⋮`** (`components/ui/dropdown-menu.tsx`), deixando só o toggle start/stop inline. **Excluir** exige digitar o nome do túnel (type-to-confirm).

## 12. Validação, decisão e estado atual

**Failover validado ao vivo (2026-07-22):**
- **Botão Testar failover**: bloqueou o endpoint ativo, DPD detectou, chaveou pro backup em **~42s**, e o auto-restore (120s) limpou o bloqueio e voltou os dois túneis.
- **Switch manual / Rollback**: virada instantânea pro backup / volta pro primário.
- **Queda real pelo FortiGate**: o usuário fez `set status down` na **interface de túnel** primária (`to-tst01`) — sem tocar na WAN física, mantendo a gerência. Monitorado do EG: a saída foi **toda pelo backup** durante a queda e **voltou pro primário ~5s após** o `set status up`. Como o admin-down manda um DELETE limpo, o chaveamento foi **imediato** (sem esperar DPD); o DPD ~30-42s só vale pra falha silenciosa/dura.

**Decisão de arquitetura (2026-07-22): opção "A" — single-connection active/standby.** Uma conexão, `remote_addrs = [primário, backup]`, os 2 SAs up em paralelo, uma rota de saída. Cobre a necessidade real (failover por queda). O **split em dois túneis route-based/VTI** (que habilitaria SLA por-membro verde-enquanto-ocioso, failover por latência e load-balance) fica **arquivado** — só reabre se o requisito virar "trocar por qualidade, não só por queda". Trade-off aceito: o membro backup aparece down-enquanto-ocioso no dashboard do FortiGate (acende sozinho no failover real).

**Estado atual**: branch `feature/ipsec-failover` completa, commitada e no origin (`452b254` → `29fa919` → `eddee80`). Homolog rodando essa versão, túnel real `to-macro01` com os 2 endpoints UP. Deploy no homolog foi **manual** (scp + rebuild + restart do agent).

**Para o release (~v1.6.0), quando o usuário der o ok**: só falta atualizar o handoff doc (`docs/handoff/`) → merge de `feature/ipsec-failover` na `main` → release. Não lançar sem o ok do usuário.
