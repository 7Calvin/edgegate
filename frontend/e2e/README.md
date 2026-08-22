# Smoke E2E (Playwright) — EdgeGate

Suite **fina** de UI: poucos testes, cada um percorrendo um caminho crítico de
ponta a ponta contra o **stack real** (docker-compose). Complementa o
`scripts/smoke_test.py` (que cobre a API) testando a camada que ele não vê: a UI.

## O que cobre

| Arquivo | Fluxo |
|---|---|
| `auth.setup.ts` | Loga como admin uma vez e salva a sessão (`e2e/.auth/admin.json`) |
| `01-login.spec.ts` | Login válido → dashboard; login inválido → erro, fica no /login |
| `02-users.spec.ts` | Criar usuário → aparecer na lista → excluir |
| `03-ldap.spec.ts` | Configurar AD/LDAP → salvar → persistir após reload |
| `04-pages.spec.ts` | Firewall / Conexões / Dashboard renderizam sem erro de JS |

MFA e os fluxos de API ficam cobertos pelo `scripts/smoke_test.py`.

## Rodar

### Opção A — Gate de release (efêmero, recomendado)

Sobe uma **cópia limpa** da aplicação (banco do zero), roda os testes e derruba
tudo no final — mesmo se falhar. É o "validar um build candidato antes de lançar".
Rode da **raiz do repo**, com o stack de dev **desligado** (ele usa a porta 443):

```powershell
# Windows
pwsh scripts/e2e.ps1
```
```bash
# Linux / CI / Git Bash
./scripts/e2e.sh
```

Só precisa do Playwright instalado uma vez (`cd frontend && npm install && npx playwright install chromium`).
O gate sobe só a camada de aplicação (`postgres, redis, backend, frontend,
traefik`) via `docker-compose.e2e.yml` com project name isolado `edgegate-e2e`;
openvpn/nat-agent/ipsec ficam de fora (o smoke não precisa).

### Opção B — Contra um stack já no ar (dev)

```bash
docker-compose up -d          # na raiz, sobe o stack de dev
cd frontend
npm install                   # 1ª vez
npx playwright install chromium
npm run test:e2e              # headless
npm run test:e2e:ui          # interativo (debug)
npm run test:e2e:report      # abre o último relatório HTML
```

> ⚠️ A Opção B mexe no **banco real** do dev: cria/apaga um usuário `e2e_user_*`
> e sobrescreve as configurações de LDAP (com `enabled:false`). Use a Opção A
> quando quiser isolamento total.

## Config por ambiente

Aponta pra outro host/credenciais via env (defaults batem com o docker-compose):

- `E2E_BASE_URL`   — default `https://localhost` (Traefik, cert self-signed)
- `E2E_ADMIN_USER` — default `admin`
- `E2E_ADMIN_PASS` — default `Admin123!@#456`

> O ponto de entrada é o **Traefik em https://localhost**, não a porta 8000 nem
> o Vite: o frontend chama a API em `/api/v1` (relativo) e é o Traefik que roteia
> `/api`→backend e `/`→frontend.
