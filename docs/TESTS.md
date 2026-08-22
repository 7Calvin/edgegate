# EdgeGate - Test Checklist

Documento para rastrear testes manuais e funcionais do sistema.

---

## Legenda
- [x] Testado e funcionando
- [ ] Pendente
- [~] Parcialmente testado / com issues

---

## 1. Autenticação

### 1.1 Login Básico
- [x] Login com credenciais válidas
- [x] Login com credenciais inválidas (erro apropriado)
- [x] Logout

### 1.2 MFA (Two-Factor Authentication)
- [x] Setup MFA - gera QR code e backup codes
- [x] Verificar código TOTP e ativar MFA
- [x] Login com MFA habilitado (pede código após senha)
- [x] Login com código MFA correto
- [x] Login com código MFA incorreto (erro)
- [x] Desabilitar MFA (com senha + código)
- [x] Bloquear desabilitar MFA quando `mfa_required=true`
- [ ] **Login com backup code** (usuário perdeu acesso ao app) - *Backend pronto, testar UI*
- [ ] Backup code uso único (segundo uso deve falhar) - *Backend pronto, testar*
- [ ] Regenerar backup codes - *Não implementado*

### 1.3 Sessão
- [ ] Token refresh automático
- [ ] Expiração de sessão
- [ ] Múltiplas sessões simultâneas

---

## 2. Usuários

### 2.1 CRUD
- [x] Listar usuários
- [x] Criar usuário (admin)
- [x] Editar usuário
- [x] Deletar usuário (com confirmação de username)
- [x] Proteção contra auto-delete (admin não pode deletar a si mesmo)

### 2.2 Status e Permissões
- [x] Toggle status ativo/inativo
- [x] Proteção contra auto-disable
- [x] Reset password com modal + copiar
- [ ] Forçar MFA para usuário específico (`mfa_required`)

---

## 3. VPN

### 3.1 Perfil VPN
- [x] Auto-criação de perfil VPN ao criar usuário
- [x] Download arquivo .ovpn
- [x] Página VPN acessível para todos os usuários
- [ ] Regenerate certificate (admin only)
- [ ] Revogar certificado

### 3.2 Conexão OpenVPN
- [ ] **Conectar com cliente OpenVPN real**
- [ ] Túnel estabelecido (tun0)
- [ ] Acesso à internet via VPN
- [ ] Acesso à rede privada (10.0.0.0/24) via VPN
- [ ] Múltiplos clientes simultâneos
- [ ] Desconexão limpa

### 3.3 CCD (Client Config Directory)
- [ ] Push de rotas automático para cliente
- [ ] IP fixo por cliente (se configurado)

---

## 4. Firewall

### 4.1 Regras Básicas
- [x] Quick Rules sincronizados (toggle)
- [x] Add Rule via modal
- [x] Delete Rule
- [x] Auto-apply em mudanças
- [x] Regras padrão criadas no startup

### 4.2 NAT / Port Forwarding
- [x] Criar regra DNAT (port forwarding)
- [x] Service presets (SSH, HTTP, HTTPS, etc.)
- [x] Auto-create firewall rule ao criar DNAT
- [ ] Testar DNAT funcionando (acesso externo → interno)
- [ ] SNAT rules

### 4.3 AWS Dual-NIC
- [ ] MASQUERADE eth0 (internet)
- [ ] MASQUERADE eth1 (rede privada)
- [ ] Forward tun0 ↔ eth0
- [ ] Forward tun0 ↔ eth1
- [ ] INPUT chain protegendo servidor

---

## 5. Connections

### 5.1 Monitoramento
- [ ] Listar conexões ativas
- [ ] Histórico de conexões
- [ ] Detalhes de conexão (IP, duração, bytes)

### 5.2 Ações
- [ ] Desconectar cliente ativo
- [ ] Bloquear IP

---

## 6. Dashboard

- [x] Estatísticas gerais
- [ ] Gráficos de uso (bandwidth)
- [ ] Conexões ativas em tempo real

---

## 7. Settings

### 7.1 Perfil
- [x] Visualizar informações do usuário
- [x] Alterar senha

### 7.2 Sistema (Admin)
- [ ] Configurações globais do sistema
- [ ] Backup/restore configurações

---

## 8. API Keys

- [ ] Criar API key
- [ ] Listar API keys
- [ ] Revogar API key
- [ ] Autenticação via API key

---

## 9. Audit Logs

- [ ] Registrar ações de usuários
- [ ] Visualizar logs no frontend
- [ ] Filtrar por usuário/ação/data
- [ ] Exportar logs

---

## 10. Infraestrutura

### 10.1 Docker
- [ ] `docker compose up` funciona sem erros
- [ ] Todos os containers healthy
- [ ] Persistência de dados (volumes)
- [ ] Restart automático

### 10.2 AWS
- [ ] Deploy em EC2
- [ ] Security Groups configurados
- [ ] Elastic IP associado
- [ ] Route tables para VPN subnet

---

## Próximos Testes Prioritários

1. [ ] Login com backup code (MFA recovery)
2. [ ] Conexão OpenVPN com cliente real
3. [ ] DNAT funcionando end-to-end
4. [ ] Docker compose full stack

---

**Última atualização**: 2026-02-01
