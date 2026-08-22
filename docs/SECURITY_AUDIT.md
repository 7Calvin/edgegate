# Relatório de Auditoria de Segurança
## EdgeGate

**Data:** 2026-02-09
**Escopo:** Full (Frontend, Backend, Configurações, VPN/IPsec)
**Auditor:** Claude Opus 4.5 (Security Reviewer Agent)

---

## Resumo Executivo

A auditoria identificou **18 vulnerabilidades** distribuídas em:

| Severidade | Quantidade |
|------------|------------|
| Crítico | 2 |
| Alto | 5 |
| Médio | 7 |
| Baixo | 4 |

---

## Vulnerabilidades Críticas 🔴

### VULN-001: Tokens JWT Armazenados em Storage Persistente

**Arquivo:** `frontend/src/stores/auth.ts:101-107`
**Tipo:** CWE-922 - Insecure Storage of Sensitive Information
**CVSS:** 8.1 (High)

**Descrição:**
Os tokens JWT (access e refresh) são persistidos em `localStorage` através do middleware `persist` do Zustand. Isso os torna vulneráveis a ataques XSS, pois JavaScript malicioso pode acessar `localStorage`.

**Código vulnerável:**
```typescript
persist(
  (set, get) => ({
    // ... state
  }),
  {
    name: 'auth-storage',
    partialize: (state) => ({
      accessToken: state.accessToken,
      refreshToken: state.refreshToken,
    }),
  }
)
```

**Recomendação:**
- Usar cookies HTTP-only com flags `Secure` e `SameSite=Strict` para refresh tokens
- Manter access token apenas em memória (state não persistido)
- Implementar token rotation

**Referências:**
- [OWASP ASVS V3.5 - Token-based Session Management](https://owasp.org/www-project-application-security-verification-standard/)
- [CWE-922](https://cwe.mitre.org/data/definitions/922.html)

---

### VULN-002: Endpoints VPN Sem Autenticação

**Arquivo:** `backend/app/api/v1/routes/vpn.py:599-634`
**Tipo:** CWE-306 - Missing Authentication for Critical Function
**CVSS:** 9.1 (Critical)

**Descrição:**
Endpoints `/api/v1/vpn/auth`, `/api/v1/vpn/connections/connect` e `/api/v1/vpn/connections/disconnect` não possuem autenticação. São chamados por scripts OpenVPN, mas podem ser acessados por qualquer pessoa.

**Código vulnerável:**
```python
@router.post("/auth")
async def vpn_authenticate(
    data: VPNAuthRequest,
    db: AsyncSession = Depends(get_db)  # SEM Depends(get_current_user)!
):

@router.post("/connections/connect")
async def vpn_client_connected(
    data: VPNConnectRequest,
    db: AsyncSession = Depends(get_db)  # SEM Depends(get_current_user)!
):

@router.post("/connections/disconnect")
async def vpn_client_disconnected(
    data: VPNDisconnectRequest,
    db: AsyncSession = Depends(get_db)  # SEM Depends(get_current_user)!
):
```

**Recomendação:**
- Implementar autenticação via API key ou IP whitelist para estes endpoints
- Usar um token de serviço interno que não seja exposto publicamente
- Validar que requisições vêm apenas do container OpenVPN

**Referências:**
- [OWASP API Security Top 10 - API2:2023 Broken Authentication](https://owasp.org/API-Security/editions/2023/en/0xa2-broken-authentication/)
- [CWE-306](https://cwe.mitre.org/data/definitions/306.html)

---

## Vulnerabilidades Altas 🟠

### VULN-003: Secrets Default em Código

**Arquivos:** Múltiplos
**Tipo:** CWE-798 - Use of Hard-coded Credentials

| Arquivo | Linha | Secret |
|---------|-------|--------|
| `backend/app/core/config.py` | 25 | `SECRET_KEY: str = "change-me-in-production"` |
| `backend/app/core/config.py` | 50 | `POSTGRES_PASSWORD: str = "change-me"` |
| `backend/app/core/config.py` | 80 | `JWT_SECRET_KEY: str = "change-me-jwt-secret"` |
| `backend/app/core/config.py` | 148 | `NAT_AGENT_TOKEN: str = "changeme-nat-token"` |
| `docker-compose.yml` | 16, 35, 62, etc | `changeme` como default |

**Recomendação:**
- Remover todos os valores default de secrets
- Falhar na inicialização se secrets obrigatórios não estiverem definidos
- Usar gerador de secrets no install.sh (já implementado parcialmente)

**Referências:**
- [CWE-798](https://cwe.mitre.org/data/definitions/798.html)

---

### VULN-004: IPsec Agent - Command Injection Potencial

**Arquivo:** `docker/ipsec-agent/app.py:76-97`
**Tipo:** CWE-78 - OS Command Injection

**Código vulnerável:**
```python
@app.route('/status/<connection_name>', methods=['GET'])
def status_connection(connection_name):
    result = run_ipsec_command(['status', connection_name])
    # connection_name vem diretamente da URL sem sanitização
```

**Recomendação:**
- Validar `connection_name` com regex: `^[a-zA-Z0-9_-]+$`
- Implementar whitelist de conexões válidas do banco de dados

**Referências:**
- [CWE-78](https://cwe.mitre.org/data/definitions/78.html)

---

### VULN-005: Rate Limiting Não Implementado

**Arquivo:** `backend/app/dependencies/auth.py:188-205`
**Tipo:** CWE-799 - Improper Control of Interaction Frequency

**Código:**
```python
class RateLimiter:
    """Rate limiter dependency (placeholder for Redis-based implementation)"""
    async def __call__(self, user: Optional[User] = Depends(get_optional_user)):
        # TODO: Implement Redis-based rate limiting
        # For now, just pass through
        pass

rate_limit_auth = RateLimiter(calls=5, period=60)  # NUNCA USADO!
```

**Recomendação:**
- Implementar rate limiting real com Redis
- Aplicar `Depends(rate_limit_auth)` em endpoints de autenticação
- Considerar usar `slowapi` ou `fastapi-limiter`

**Referências:**
- [OWASP ASVS V2.2.1 - Anti-automation Controls](https://owasp.org/www-project-application-security-verification-standard/)

---

### VULN-006: PSK Armazenado em Texto Plano no Banco

**Arquivo:** `backend/app/models/ipsec.py:63`
**Tipo:** CWE-312 - Cleartext Storage of Sensitive Information

**Código:**
```python
psk = Column(Text)  # Pre-shared key (should be encrypted in production)
```

**Recomendação:**
- Criptografar PSK antes de armazenar (AES-256-GCM)
- Usar serviço de gerenciamento de secrets (HashiCorp Vault, AWS Secrets Manager)
- Descriptografar apenas no momento de uso

**Referências:**
- [CWE-312](https://cwe.mitre.org/data/definitions/312.html)

---

### VULN-007: Container NAT-Agent com Privileged Mode

**Arquivo:** `docker-compose.yml:154`
**Tipo:** CWE-250 - Execution with Unnecessary Privileges

**Código:**
```yaml
nat-agent:
  privileged: true  # ACESSO ROOT COMPLETO AO HOST
  cap_add:
    - NET_ADMIN
```

**Recomendação:**
- Remover `privileged: true`
- Usar apenas capabilities necessárias: `CAP_NET_ADMIN`, `CAP_NET_RAW`
- Considerar usar seccomp profile restritivo

**Referências:**
- [CWE-250](https://cwe.mitre.org/data/definitions/250.html)

---

## Vulnerabilidades Médias 🟡

### VULN-008: CORS Permissivo em Produção

**Arquivo:** `backend/app/main.py:41-47`
**Tipo:** CWE-942 - Permissive Cross-domain Policy

**Código:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],  # MUITO PERMISSIVO
    allow_headers=["*"],  # MUITO PERMISSIVO
)
```

**Recomendação:**
- Especificar métodos: `["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]`
- Especificar headers: `["Authorization", "Content-Type"]`

---

### VULN-009: Ausência de Proteção CSRF

**Tipo:** CWE-352 - Cross-Site Request Forgery

**Descrição:**
Não foi encontrada nenhuma implementação de proteção CSRF no projeto.

**Recomendação:**
- Implementar CSRF tokens para operações state-changing
- Usar `SameSite=Strict` em cookies de sessão
- Considerar double-submit cookie pattern

---

### VULN-010: Arquivo .env com Secrets Reais no Repositório

**Arquivo:** `.env` e `.gitignore`
**Tipo:** CWE-540 - Information Exposure Through Source Code

**Problema:**
O `.gitignore` tem `.env` comentado, permitindo que secrets sejam commitados.

**Recomendação:**
- Descomentar `.env` no `.gitignore`
- Remover secrets reais do repositório (requer rotação de chaves)
- Usar `.env.example` apenas com valores placeholder

---

### VULN-011: TrustedHostMiddleware com Wildcard

**Arquivo:** `backend/app/main.py:50-54`
**Tipo:** CWE-346 - Origin Validation Error

**Código:**
```python
if not settings.DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # PERMITE QUALQUER HOST
    )
```

**Recomendação:**
- Configurar hosts permitidos explicitamente via variável de ambiente

---

### VULN-012: Ausência de Content-Security-Policy

**Arquivo:** `docker/nginx/conf.d/default.conf:29-32`
**Tipo:** CWE-693 - Protection Mechanism Failure

**Headers faltando:**
- Content-Security-Policy
- Strict-Transport-Security

**Recomendação:**
```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

---

### VULN-013: Validação de PSK Mínima

**Arquivo:** `backend/app/schemas/ipsec.py:39`
**Tipo:** CWE-521 - Weak Password Requirements

**Código:**
```python
psk: Optional[str] = Field(None, min_length=8, max_length=256)
```

**Recomendação:**
- Aumentar `min_length` para 32
- Adicionar validação de complexidade

---

### VULN-014: Logout Não Invalida Token

**Arquivo:** `backend/app/api/v1/routes/auth.py:102-114`
**Tipo:** CWE-613 - Insufficient Session Expiration

**Código:**
```python
@router.post("/logout", response_model=MessageResponse)
async def logout(user: User = Depends(get_current_user)):
    # TODO: Add token to blacklist in Redis
    return MessageResponse(message="Logged out successfully")
```

**Recomendação:**
- Implementar blacklist de tokens no Redis
- Reduzir tempo de expiração do access token

---

## Vulnerabilidades Baixas 🟢

### VULN-015: Swagger/OpenAPI Exposto em Produção

**Arquivo:** `backend/app/main.py:32-34`

**Recomendação:**
```python
docs_url=None if not settings.DEBUG else "/docs"
```

---

### VULN-016: Informação de Versão Exposta

**Arquivo:** `backend/app/main.py:146-164`

**Recomendação:**
- Não expor versão e ambiente em endpoints públicos em produção

---

### VULN-017: Debug Habilitado por Default

**Arquivo:** `docker-compose.yml:68`

**Código:**
```yaml
- DEBUG=${DEBUG:-true}  # DEFAULT TRUE!
```

**Recomendação:**
- Mudar default para `false`

---

### VULN-018: Senhas em Process Listing

**Arquivo:** `backend/scripts/start.sh:30`

**Recomendação:**
- Usar arquivo de configuração ou variável de ambiente sem interpolar em string de comando

---

## Aspectos Positivos ✅

| Aspecto | Status |
|---------|--------|
| SQLAlchemy ORM (sem SQL injection) | ✅ |
| Bcrypt para hash de senhas | ✅ |
| MFA/2FA com TOTP e backup codes | ✅ |
| Validação de entrada com Pydantic | ✅ |
| Headers básicos (X-Frame-Options, X-Content-Type-Options) | ✅ |
| Redirect HTTP→HTTPS no nginx | ✅ |
| Container backend não-root (vpnuser) | ✅ |
| Ciphers IPsec seguros (AES-256-SHA256) | ✅ |

---

## Plano de Remediação

### Fase 1 - Imediato (Crítico)
- [ ] Mover tokens para cookies HTTP-only
- [ ] Proteger endpoints VPN com autenticação de serviço

### Fase 2 - Curto Prazo (Alto)
- [ ] Remover secrets default do código
- [ ] Implementar rate limiting com Redis
- [ ] Criptografar PSK no banco de dados
- [ ] Remover modo privilegiado do nat-agent
- [ ] Validar input no ipsec-agent

### Fase 3 - Médio Prazo (Médio)
- [ ] Adicionar CSP e HSTS
- [ ] Implementar blacklist de tokens no logout
- [ ] Configurar CORS restritivo
- [ ] Implementar proteção CSRF
- [ ] Remover .env do repositório

### Fase 4 - Melhoria Contínua (Baixo)
- [ ] Desabilitar Swagger em produção
- [ ] Remover informações de versão
- [ ] Configurar DEBUG=false por default

---

## Histórico

| Data | Ação |
|------|------|
| 2026-02-09 | Auditoria inicial completa |

---

*Relatório gerado pelo Security Reviewer Agent*
