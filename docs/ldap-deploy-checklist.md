# Checklist de Deploy — Autenticação AD/LDAP

Passo a passo para colocar a autenticação por Active Directory em produção.
Branch: `feat/ldap-ad-auth`. Data: 2026-07-17.

> Regra de ouro: a instalação continua **base local** até um admin habilitar o AD na UI.
> Nada quebra enquanto o toggle estiver desligado.

---

## 1. Pré-requisitos de rede

- [ ] O **backend** (`edgegate-backend`) precisa alcançar o **Domain Controller** na **porta 389/TCP**.
  ```bash
  # de dentro do container backend:
  docker exec edgegate-backend sh -c 'nc -zv <IP_DO_DC> 389'   # ou: python -c "import socket; socket.create_connection(('<IP_DO_DC>',389),5)"
  ```
- [ ] Se o DC está em outra rede, garantir rota/firewall do host da VPN até o DC.
- [ ] Lembrar: LDAP **simples (389)** — senha do AD trafega em claro **nessa perna interna**
  (backend → DC). Manter em rede confiável.

---

## 2. No Active Directory (uma vez)

- [ ] **Grupo da VPN**: criar (ou escolher) o grupo que concede acesso, ex.:
  `CN=VPN-Users,OU=Groups,DC=empresa,DC=com`. Anotar o **DN completo**.
  - Grupos aninhados funcionam: pode colocar o grupo `Financeiro` dentro de `VPN-Users`
    e os usuários dentro de `Financeiro`.
- [ ] **Service account de bind**: um usuário comum (sem privilégios especiais) só para
  fazer o bind e pesquisar o diretório, ex.: `CN=svc-vpn,OU=Service,DC=empresa,DC=com`.
  - Senha que não expira (ou processo de rotação definido).
- [ ] **Base de busca**: geralmente a raiz do domínio, ex.: `DC=empresa,DC=com`.
- [ ] **Atributo de login**: normalmente `sAMAccountName` (o "usuário" que a pessoa digita).
- [ ] ⚠️ **LDAP signing**: se o DC estiver com *"Domain controller: LDAP server signing
  requirements = Require signing"*, o bind simples na 389 é **rejeitado**. Conferir essa
  policy antes — é a causa nº1 de "bind failed" com credenciais corretas.

> **AD moderno exige bind assinado (NTLM).** DCs recentes recusam bind simples em
> texto claro na 389 (`strongerAuthRequired` — "requires integrity checking"). Por isso
> o padrão é **NTLM assinado** (toggle ligado na UI), que conecta na mesma 389, **sem
> LDAPS e sem mudar o AD** — é o mesmo mecanismo do FortiGate. No modo NTLM, informe o
> **Domínio (NetBIOS)** e a conta de serviço como **sAMAccountName** (ou `DOMÍNIO\usuário`),
> não o DN completo.

Anote para usar na UI (modo NTLM — recomendado):
```
Servidor:            <IP ou FQDN do DC>       ex.: 10.10.22.60
Porta:               389
Bind NTLM assinado:  LIGADO
Domínio (NetBIOS):   CALVIN
Conta de serviço:    seven            (sAMAccountName, ou CALVIN\seven)
Senha do bind:       ********
Base de busca:       DC=calvin,DC=local
Atributo de login:   sAMAccountName
Grupo da VPN (DN):   CN=VPN-Users,OU=Grupos,DC=calvin,DC=local
```
(Se o seu DC ainda permitir bind simples, desligue o toggle NTLM e use o Bind DN completo.)

---

## 3. Deploy no servidor

- [ ] Atualizar o código para a branch (ou fazer merge em `main` antes):
  ```bash
  cd /caminho/edgegate
  git fetch origin
  git checkout feat/ldap-ad-auth      # ou: git merge feat/ldap-ad-auth em main
  ```
- [ ] Rebuild do backend (nova dependência `ldap3`) e do frontend, e subir:
  ```bash
  docker compose build backend frontend
  docker compose up -d backend frontend
  ```
- [ ] A **migration `008`** roda sozinha no boot do backend (`scripts/start.sh` executa
  `alembic upgrade head`). Confirmar:
  ```bash
  docker compose logs backend | grep -i alembic
  docker exec edgegate-backend alembic current      # deve mostrar 008 (head)
  ```
  Se precisar aplicar manualmente:
  ```bash
  docker exec edgegate-backend alembic upgrade head
  ```
- [ ] Rodar os testes unitários (rápidos, sem AD):
  ```bash
  docker exec edgegate-backend pytest -q
  ```

---

## 4. Configurar pela UI

- [ ] Entrar no painel como **admin** → **Configurações → Autenticação Active Directory (LDAP)**.
- [ ] Preencher com os valores anotados no passo 2.
- [ ] Clicar **Testar conexão** → deve retornar "Conexão bem-sucedida".
  - Falhou? Ver Troubleshooting abaixo (não salve/ligue ainda).
- [ ] Ligar o toggle **Habilitar autenticação AD** → **Salvar**.

---

## 5. Validar (end-to-end)

- [ ] **Usuário no grupo**: coloque um usuário de teste no grupo da VPN no AD →
  conectar na VPN com usuário/senha do AD → **conecta**. Confirmar que apareceu na lista
  de conexões (o usuário sombra foi criado no 1º login).
  ```bash
  docker compose logs backend | grep -i "JIT-provisioned"
  ```
- [ ] **Usuário fora do grupo**: usuário válido do AD mas fora do grupo → **negado**.
- [ ] **Usuário local**: uma conta local existente (ex.: admin) → **continua conectando**
  normalmente com o AD ligado.
- [ ] **Grupo aninhado**: colocar o usuário num subgrupo dentro do grupo da VPN → **conecta**.
- [ ] Verificar logs de auth do OpenVPN e do backend se algo falhar.

---

## 6. Rollback (se necessário)

- [ ] **Reversão rápida (sem deploy)**: desligar o toggle na UI → volta 100% para base local
  na hora. (Recomendado para incidentes.)
- [ ] **Reversão de código**:
  ```bash
  git checkout main        # versão anterior
  docker compose build backend frontend && docker compose up -d backend frontend
  ```
- [ ] **Reversão da migration** (só se realmente precisar remover as colunas/tabela):
  ```bash
  docker exec edgegate-backend alembic downgrade 007
  ```
  > Cuidado: isso remove `ldap_settings` e a coluna `auth_source`. Usuários sombra do AD
  > perdem a marcação de origem. Prefira o rollback pelo toggle.

---

## 7. Troubleshooting

| Sintoma | Causa provável | Ação |
|--------|----------------|------|
| `strongerAuthRequired` / "integrity checking" | Modo simples num DC que exige signing | **Ligar o toggle NTLM** (assina a sessão na 389) |
| "Testar conexão" falha em NTLM com credenciais certas | Domínio NetBIOS ausente/errado, ou conta como DN | Preencher **Domínio (NetBIOS)** e usar sAMAccountName na conta de serviço |
| "Bind failed (service account)" | Conta/senha errada, ou conta bloqueada | Conferir conta de serviço (sAMAccountName) e senha |
| Usuário do AD autentica mas conexão não aparece | Usuário sombra não criado / lookup | Ver logs `JIT-provisioned`; conferir `common_name` do OpenVPN |
| Todos os usuários do AD negados | DN do grupo errado ou base de busca errada | Revisar `required_group_dn` e `search_base` |
| Login trava/lento | DC inacessível/timeout | Conferir rota/porta 389; `timeout` curto já limita o impacto |
| Usuário local parou de entrar | (não deve ocorrer) | Local independe do AD; checar senha/conta ativa |

Comandos úteis:
```bash
docker compose logs -f backend                    # erros de LDAP/auth
docker exec edgegate-openvpn tail -f /etc/openvpn/logs/auth.log
docker exec edgegate-backend alembic current
```
