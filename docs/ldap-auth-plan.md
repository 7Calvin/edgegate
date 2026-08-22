# Plano: Autenticação LDAP/Active Directory para OpenVPN (base híbrida local + AD)

**Status:** Implementado e **validado ao vivo** contra AD real · **Data:** 2026-07-17

> ## Atualização (validação em AD real 10.10.22.60 / calvin.local)
>
> O DC (Windows moderno) **recusa bind simples em texto claro na 389** com
> `strongerAuthRequired` — exige canal com integridade (signing). Confirmado com
> `ldap3` **e** `ldapsearch`; StartTLS/LDAPS indisponíveis (sem certificado no DC).
> Mensagem do próprio DC: *"requires binds to turn on integrity checking if SSL/TLS
> are not already active"*.
>
> **Solução (a mesma que um FortiGate usa): bind NTLM assinado sobre a 389** — sem
> LDAPS, sem tocar no AD. Implementado com `msldap` (pure-Python). Adicionados:
> `use_ntlm` (default true) e `ad_domain` (NetBIOS) nas settings (migration 009).
>
> Validado ponta-a-ponta: testar conexão OK; `vpn/auth` de usuário **no** grupo → 200 +
> JIT (`auth_source=ad`); **fora** do grupo → 401; login local do admin intacto.
> Detalhes técnicos: `docs/ldap-deploy-checklist.md`.

> Implementação concluída (backend + frontend), migrations 008 e 009 aplicadas.

## Objetivo

Permitir que o OpenVPN autentique usuários contra o **Active Directory**, liberando
acesso **com base em grupo** (usuário no grupo da VPN no AD → conecta; fora do grupo →
não conecta), **mantendo simultaneamente** a base de usuários **local** existente.

## Viabilidade

**Sim, é possível usar as duas bases ao mesmo tempo.** Toda a autenticação da VPN já
passa por um único ponto:

```
OpenVPN → docker/openvpn/scripts/auth.sh → POST /api/v1/vpn/auth
        → AuthService.authenticate_user() → banco local (bcrypt)
```

Como `authenticate_user()` é o único funil, o AD entra **só nessa função**. Não há
mudança no OpenVPN nem no `auth.sh`.

Hoje o LDAP é apenas uma flag desligada (`FEATURE_ENABLE_LDAP=false`) com placeholders
no `.env.example` — **sem implementação real**.

## Decisões

| Tema | Decisão |
|------|---------|
| Controle liga/desliga | **Pelo frontend** (settings em banco), não por `.env`. Default install = base local |
| Transporte LDAP | **LDAP simples na 389, sem TLS** (decisão do usuário) |
| Ordem de auth | **Cada usuário tem sua fonte.** Conta local autentica sempre na base local (independe do AD, ligado ou não); usuário AD autentica no AD. Em colisão de mesmo username, a conta **local vence** (protege admin/break-glass) |
| Provisionamento | **JIT** — cria "usuário sombra" local no 1º login do AD |
| MFA para AD | **Sem MFA local para AD** por enquanto (confia em senha + grupo do AD) |

> ⚠️ **LDAP simples (389):** a senha do AD trafega em texto claro na rede interna.
> Aceito pelo usuário. Possível ponto de falha: DCs com *"LDAP server signing
> requirements = Require signing"* rejeitam bind simples na 389 — checar no AD se o
> bind falhar.

## Fluxo de autenticação híbrido

`AuthService.authenticate_user()` passa a:

1. Buscar usuário local pelo `username`.
2. **Se existe local com `password_hash` utilizável** (admin, service account, conta
   local) → valida no banco, como hoje.
3. **Senão** → chamar `LdapService.authenticate()`:
   a. Bind **LDAP simples (porta 389, sem TLS)** com as credenciais do usuário
      (ou service-bind + rebind).
   b. Buscar o objeto do usuário e ler `memberOf`.
   c. Liberar **apenas** se pertencer a `LDAP_REQUIRED_GROUP`
      (usando `LDAP_MATCHING_RULE_IN_CHAIN` = `1.2.840.113556.1.4.1941` para
      **grupos aninhados** do AD).
   d. Se autenticou e está no grupo → **JIT provisioning**: cria/atualiza o usuário
      local (origem `ad`, sem senha local, limites default) para que quotas, conexões
      e firewall por usuário funcionem.

## Controle por grupo (núcleo do requisito)

- Config `LDAP_REQUIRED_GROUP` (DN do grupo da VPN, ex.:
  `CN=VPN-Users,OU=Groups,DC=empresa,DC=com`).
- Checagem via filtro:
  `(&(sAMAccountName=%s)(memberOf:1.2.840.113556.1.4.1941:=<group_dn>))`
- Remover do grupo no AD → próxima tentativa de conexão é negada.
- (Opcional futuro) mapear vários grupos → perfis/limites diferentes.

## Pontos de atenção confirmados no código

1. **JIT é obrigatório.** `POST /api/v1/vpn/auth/connections/connect`
   (`backend/app/api/v1/routes/vpn.py:656`) retorna **404 se o usuário não existe na
   tabela `users`**. Sem o usuário sombra, o login passaria mas o **registro da conexão
   falharia**, e quotas/firewall/limites por usuário não se aplicariam.
2. **Controle em runtime pelo frontend.** Hoje as settings são só leitura do `.env`
   (`admin.py:111` só lê `settings.FEATURE_ENABLE_LDAP`). Para ligar/desligar pela UI
   é preciso persistir a config do AD em banco (ver "Controle pelo frontend").
3. **LDAP simples (389):** senha do AD em texto claro na rede interna (decisão aceita).
   Atenção a DCs com signing obrigatório (rejeitam bind simples).
4. **MFA** atual mora no banco local (`mfa_secret`); usuários AD não teriam MFA por
   esse mecanismo (ver decisão).
5. **Biblioteca:** `ldap3` (Python puro — sem compilação no Docker), não `python-ldap`.

## Controle pelo frontend

Requisito: ligar/desligar AD e configurar o servidor **pela UI**, sem editar `.env`.
Instalação default continua **base local** (toggle desligado / tabela vazia).

- **Tabela `ldap_settings`** (linha única) no banco: `enabled`, `server`, `port` (389),
  `bind_dn`, `bind_password`, `search_base`, `user_attr` (`sAMAccountName`),
  `required_group_dn`, `timeout`. Grupos aninhados: **sempre ligados** (via IN_CHAIN),
  sem toggle na UI.
- **API admin:** `GET/PUT /api/v1/admin/ldap-settings` + `POST .../test`
  (bind de teste no AD, retorna ok/erro sem persistir).
- **Frontend:** aba em Admin/Settings com formulário + toggle "Habilitar AD" +
  botão "Testar conexão".
- `FEATURE_ENABLE_LDAP` do `.env` vira apenas master-switch opcional; o controle do
  dia a dia fica no banco/UI.

## Mudanças previstas

### Backend
- `backend/requirements.txt` → adicionar `ldap3`.
- `backend/app/models/ldap_settings.py` → **novo**: tabela de config do AD (linha única),
  gerenciada pela UI. Migration Alembic.
- `backend/app/services/ldap_service.py` → **novo**: lê config do banco;
  `authenticate(username, password)` → `(ok, attrs, error)`; bind LDAP 389, busca e
  checagem de grupo (nested via IN_CHAIN). Também `test_connection()` para o botão da UI.
- `backend/app/api/v1/routes/admin.py` → `GET/PUT /admin/ldap-settings` + `POST .../test`.
- `backend/app/services/auth_service.py` → `authenticate_user()` híbrido (local-first,
  AD-fallback) + JIT provisioning (`_provision_ldap_user`).
- `backend/app/models/user.py` → campo `auth_source` (`local` | `ad`), default `local`;
  `password_hash` nullable para contas AD. Migration Alembic.

### Frontend
- Aba **Admin/Settings → Autenticação AD**: formulário (servidor, 389, bind DN/senha,
  base, grupo da VPN), toggle "Habilitar AD", botão "Testar conexão".
- `api/client.ts` + `types/index.ts` → endpoints/tipos de `ldap-settings`.

### Sem mudança
- `docker/openvpn/scripts/auth.sh` (continua chamando o mesmo endpoint).
- OpenVPN server config.

## Passos de implementação

1. `ldap3` no requirements; model + migration de `ldap_settings`.
2. Migration: `users.auth_source` + `password_hash` nullable.
3. `LdapService` (config do banco, bind LDAP 389, checagem de grupo aninhado, test).
4. API admin `ldap-settings` (GET/PUT/test).
5. Integrar no `authenticate_user()` (local-first, AD-fallback) + JIT provisioning.
6. Frontend: página de config + toggle + testar conexão.
7. Testes: conta local pura; conta AD no grupo (sucesso); conta AD fora do grupo
   (negado); AD indisponível (fallback local não quebra); 1º login cria usuário sombra;
   toggle desligado = comportamento atual intacto.
8. Doc de operação (configurar no AD: grupo da VPN, service account de bind).

## Riscos / mitigações

- **AD fora do ar** → local-first garante que admin ainda entra; falha de LDAP é tratada
  como "auth negada" para contas AD, sem derrubar o endpoint.
- **Timeout de LDAP** travando o login do OpenVPN → timeouts curtos (2–5s) no `ldap3`.
- **Senha em texto claro (389)** → risco aceito; restringir a rede interna/confiável.
- **DC exige LDAP signing** → bind simples na 389 é rejeitado; documentar checagem no AD.
- **Grupos aninhados ignorados** → usar matching rule IN_CHAIN.

## Arquivos alterados/criados (branch `feat/ldap-ad-auth`)

**Backend**
- `backend/requirements.txt` — `ldap3==2.9.1`.
- `backend/app/models/ldap_settings.py` — **novo** model (linha única).
- `backend/app/models/user.py` — enum `AuthSource`, coluna `auth_source`,
  `password_hash` nullable, `is_ad_user`.
- `backend/app/models/__init__.py` — registra `LdapSettings` / `AuthSource`.
- `backend/alembic/versions/20260717_008_add_ldap_settings_and_auth_source.py` — **novo**.
- `backend/app/services/ldap_service.py` — **novo** (`LdapService`).
- `backend/app/services/auth_service.py` — `authenticate_user()` híbrido + `_authenticate_ad`
  + `_provision_ad_user` (JIT).
- `backend/app/schemas/ldap.py` — **novo** (settings/test schemas).
- `backend/app/api/v1/routes/admin.py` — `GET/PUT /admin/ldap-settings` + `.../test`.
- `backend/app/api/v1/routes/vpn.py` — busca de usuário no connect agora case-insensitive.

**Frontend**
- `frontend/src/api/client.ts` — `adminApi` LDAP + tipos.
- `frontend/src/components/LdapSettingsCard.tsx` — **novo** (form + toggle + testar).
- `frontend/src/pages/SettingsPage.tsx` — inclui o card (admin-only).

**Config/docs**
- `.env.example` — LDAP agora é gerenciado pela UI (removidas vars antigas).

**Testes (mockados — sem AD/DB)**
- `backend/pytest.ini`, `backend/tests/conftest.py`
- `backend/tests/test_ldap_service.py` — filtro de grupo (IN_CHAIN), fora do grupo,
  senha errada, falha de bind, escaping anti-injection (ldap3 mockado).
- `backend/tests/test_auth_hybrid.py` — local funciona com AD ligado; senha local errada
  não cai no AD; AD no grupo → sucesso + JIT; fora do grupo → negado; AD desligado →
  erro genérico (sessão mockada + LdapService patchado).

## Como testar

### Testes unitários (rápidos, sem AD nem banco)
```bash
docker compose ... exec backend pytest        # ou: cd backend && pytest
```

### End-to-end (com AD real)

1. `docker compose ... exec backend alembic upgrade head` (aplica a migration 008).
2. Rebuild do backend (novo dep `ldap3`) e do frontend.
3. UI: **Configurações → Autenticação AD** → preencher servidor/bind/base/grupo →
   **Testar conexão** → **Salvar** com o toggle ligado.
4. Cenários:
   - Usuário no grupo da VPN no AD → conecta (e cria o usuário sombra no 1º login).
   - Usuário fora do grupo → negado.
   - Usuário local existente → continua conectando normalmente (AD ligado).
   - Toggle desligado → comportamento idêntico ao atual (só base local).
