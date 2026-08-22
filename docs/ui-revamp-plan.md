# Plano de Revamp — Dashboard, Navegação & correções (rumo a v1.3.x)

> Documento **vivo** de consolidação. Objetivo: juntar TODAS as ideias antes de
> começar a codar, decidir escopo e sequência. Nada aqui está implementado ainda,
> salvo o que estiver marcado ✅.

## 0. Estado atual (contexto)
- Branch `feat/ldap-ad-auth` com LDAP/AD (NTLM), badge AD, abas em Configurações,
  busca Ctrl+K, e edição inline de CIDRs no Firewall — **pronto e testado em prod de teste**,
  ainda **não commitado**.
- Versão atual: **v1.2.6**. Release deploya a última tag (via `scripts/release.ps1`, roda na `main`).
- Sampler de throughput: OpenVPN apenas, a cada **300s**, retenção 48h.

---

## 1. Bug — duração/bytes = 0 em conexão de usuário AD  🔴 (quick win)
**Sintoma:** conexão do usuário AD `seven` aparece com duração 0 e tráfego 0 em Conexões.

**Causa raiz (confirmada por log do OpenVPN + linha no banco):**
- No connect, `record_connection` grava `vpn_ip` **só a partir do profile local**
  (`connection_service.py:159`). Usuário AD não tem profile → `vpn_ip = NULL`.
- O connect script **envia** o `vpn_ip` real (`ifconfig_pool_remote_ip`), mas o endpoint
  não o repassa (`vpn.py:669`).
- No disconnect, `/connections/disconnect` casa por `vpn_ip == data.vpn_ip AND status=ACTIVE`.
  Com `vpn_ip=NULL` na linha, **não casa** → duração/bytes reais (2510s, 206MB/7.5MB no log)
  são descartados. O reconciliador depois fecha a linha só com `disconnected_at`.

**Fix (pequeno, backend):**
- `record_connection(...)`: aceitar `vpn_ip` e usar `vpn_ip or (profile.assigned_ip if profile else None)`.
- `vpn.py` connect endpoint: passar `vpn_ip=data.vpn_ip`.
- (opcional, robustez) disconnect: fallback de match por `username` quando `vpn_ip` não casar.

**Recomendação:** entra **junto no release do AD (v1.3.0)** — sem isso o AD não fica redondo.

---

## 2. Release pendente — LDAP/AD + Firewall  🟡
- Commits separados por feature na `main`:
  - `feat(auth): LDAP/AD via NTLM + badge/UI/busca`
  - `feat(firewall): edição inline de CIDRs nas regras rápidas`
  - `fix(connections): registrar vpn_ip do OpenVPN p/ duração/bytes de usuário AD`  (item 1)
- Usuário lança `.\scripts\release.ps1 minor` → **v1.3.0**.

---

## 3. Dashboard redesign
### 3a. Filtros de janela no throughput  🟢 (barato)
- Backend já aceita `1h|6h|24h|7d`; frontend está chumbado em `'24h'`. Só adicionar seletor.
- **"5m" não é viável hoje** (sampler a cada 300s → 1 ponto). Precisaria sampler rápido (10–15s) = tarefa à parte.

### 3b. Throughput de IPsec  🟠 (médio)
- Sampler novo lendo bytes do StrongSwan (`swanctl --list-sas`: `bytes-in/bytes-out`).
- Coluna `source` (`openvpn`/`ipsec`) em `bandwidth_samples` + migration.
- Série extra / toggle "OpenVPN / IPsec / Total" no gráfico.

### 3c. Card "Serviços"  🟢 (bom valor)
Grid de saúde com status + link rápido; substitui os 2 cards grandes de baixo (redundantes):
- OpenVPN, StrongSwan/IPsec, Firewall, AD/LDAP, (futuro) Backup FTP.
- Já temos status de quase tudo; Firewall/FTP precisam de mini status-endpoint.

### 3d. Card "Servidor" → dividir  🟢
- **Dados:** hostname, SO, IPs, certificado, versão/updates.
- **Observabilidade:** meters CPU/mem/disco + gráfico de throughput.

---

## 4. Navegação / IA
### 4a. Menu "VPNs" (agrupar OpenVPN + IPsec)  🟢
**Referência de design: console FortiGate / FortiOS 8** — sidebar com seções
colapsáveis, ícones por grupo, item ativo destacado, densidade alta. Espelhar a
organização por domínio funcional (rede, VPN, política, log/monitor).
Sidebar com grupos colapsáveis. Proposta de IA:
```
Dashboard
VPNs      ▸ OpenVPN · IPsec Site-to-Site
Rede      ▸ Firewall · Proxy Reverso · (NAT futuro)
Usuários
Conexões
Auditoria
Configurações (abas: Conta, Autenticação AD, …)
```
- Ctrl+K continua achando tudo por keyword (itens `hidden` já suportados).
- Custo: introduzir grupo colapsável (hoje a sidebar é lista simples).

---

## 5. Ideias em aberto (a preencher)
> _Espaço para as outras ideias do Calvin — cola aqui que eu organizo._
- Backup por FTP (mencionado como futuro — vira serviço no card + página própria?).
- …

---

## 6. Sequência proposta
1. **Ship já:** itens 1 (fix duração AD) + 2 (release v1.3.0).
2. **Ciclo dashboard/nav** (branch nova, ex. `feat/dashboard-nav-revamp`), ordem por custo/valor:
   - 3a filtros de janela → 4a menu VPNs → 3c card Serviços → 3d split Servidor → 3b throughput IPsec.
3. Reavaliar itens da seção 5 conforme forem definidos.
