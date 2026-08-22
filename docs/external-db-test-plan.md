# Teste de PostgreSQL Externo (Nativo no Host)

## Contexto

O projeto já suporta banco de dados externo via `install.sh` (opção [E]), mas nunca foi testado em produção real. O objetivo é instalar um PostgreSQL nativo neste Linux, migrar/testar a comunicação com o backend que roda em Docker, validando todo o fluxo de DB externo.

**Setup atual:** PostgreSQL 17 rodando como container Docker (`edgegate-postgres`), acessível internamente via hostname `postgres` na rede Docker `172.20.0.0/16`.

## Plano de Execução

### Passo 1 - Instalar PostgreSQL 17 nativo

Ubuntu 24.04 vem com PostgreSQL 16 nos repos padrão. Para manter compatibilidade com o PG 17 do Docker, vamos adicionar o repo oficial do PostgreSQL:

```bash
# Adicionar repo oficial PostgreSQL
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt noble-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update

# Instalar PostgreSQL 17
sudo apt install -y postgresql-17
```

Resultado: PostgreSQL 17 rodando na porta **5433** (para não conflitar com o 5432 do Docker).

### Passo 2 - Configurar PostgreSQL nativo

1. **Alterar porta para 5433** em `/etc/postgresql/17/main/postgresql.conf`:
   ```
   port = 5433
   ```

2. **Permitir conexões do Docker** em `/etc/postgresql/17/main/pg_hba.conf`:
   ```
   # Conexões dos containers Docker (rede bridge)
   host    all    all    172.17.0.0/16    md5
   host    all    all    172.20.0.0/16    md5
   ```

3. **Bind em todas as interfaces** em `postgresql.conf`:
   ```
   listen_addresses = '*'
   ```

4. **Restart do serviço:**
   ```bash
   sudo systemctl restart postgresql@17-main
   ```

### Passo 3 - Criar database e usuário

```bash
sudo -u postgres psql -p 5433 << 'SQL'
CREATE USER edgegate_admin_ext WITH PASSWORD 'TestExtDB2026!';
CREATE DATABASE edgegate_ext OWNER edgegate_admin_ext;
GRANT ALL PRIVILEGES ON DATABASE edgegate_ext TO edgegate_admin_ext;
\c edgegate_ext
GRANT ALL ON SCHEMA public TO edgegate_admin_ext;
SQL
```

- **User:** `edgegate_admin_ext`
- **Password:** `TestExtDB2026!`
- **Database:** `edgegate_ext`
- **Porta:** `5433`

Usamos nomes distintos (`_ext`) para não confundir com o DB do Docker.

### Passo 4 - Testar conectividade do container

Antes de mudar a config, validar que o backend Docker consegue alcançar o PostgreSQL no host:

```bash
# Testar via container backend
sudo docker exec edgegate-backend python3 -c "
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect('postgresql://edgegate_admin_ext:TestExtDB2026!@172.20.0.1:5433/edgegate_ext')
    version = await conn.fetchval('SELECT version()')
    print(f'Connected: {version}')
    await conn.close()
asyncio.run(test())
"
```

O IP `172.20.0.1` é o gateway da rede Docker bridge (`br-7966f84f6bcc`) que o backend usa, e resolve para o host.

### Passo 5 - Apontar o backend para o DB externo

Editar o `.env` de produção (`/opt/edgegate/config/.env`):

```env
# De:
DB_TYPE=local
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Para:
DB_TYPE=external
POSTGRES_HOST=172.20.0.1
POSTGRES_PORT=5433
POSTGRES_DB=edgegate_ext
POSTGRES_USER=edgegate_admin_ext
POSTGRES_PASSWORD=TestExtDB2026!
```

### Passo 6 - Restart do backend (sem recriar o container postgres)

```bash
cd /opt/edgegate
sudo docker compose restart backend
```

O backend ao iniciar vai:
1. Conectar no DB externo (via `DATABASE_URL` computado dos env vars)
2. Rodar `alembic upgrade head` (cria todas as tabelas no DB novo/vazio)
3. Rodar `init_db()` (cria admin, regras de firewall padrão)

**Nota:** O container `edgegate-postgres` continua rodando mas o backend não o usa mais. Podemos pará-lo opcionalmente.

### Passo 7 - Validação

1. **Checar logs do backend** - migrations rodaram sem erro?
   ```bash
   sudo docker logs edgegate-backend --tail=50 2>&1 | grep -E "(migration|alembic|database|error)"
   ```

2. **Verificar tabelas no DB externo:**
   ```bash
   sudo -u postgres psql -p 5433 -d edgegate_ext -c "\dt"
   ```

3. **Testar login na UI** - admin deve funcionar (foi recriado pelo init_db)

4. **Testar Connections page** - deve mostrar "No active connections" (DB limpo)

5. **Verificar que VPN connections são registradas** - conectar um client e ver se aparece

### Passo 8 - Rollback (voltar para DB Docker)

Para desfazer, basta reverter o `.env`:

```env
DB_TYPE=local
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=edgegate
POSTGRES_USER=edgegate_admin
POSTGRES_PASSWORD=9B5WE0Jfvkg7P8r3LsVg6v42
```

E reiniciar: `sudo docker compose restart backend`

---

## Resumo

| Item | Valor |
|------|-------|
| PostgreSQL version | 17 (repo oficial) |
| Porta | 5433 (evita conflito com Docker 5432) |
| Database | `edgegate_ext` |
| User | `edgegate_admin_ext` |
| Host (visto do Docker) | `172.20.0.1` |
| Schema | Criado automaticamente pelo Alembic + init_db |
| Rollback | Reverter .env e restart backend |
