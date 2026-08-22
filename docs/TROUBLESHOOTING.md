# Troubleshooting - EdgeGate

## Problemas Comuns em Produção

### 1. Erro: "Permission denied: '/app/data/server_config.json'"

**Causa:** Permissões incorretas no volume `/app/data`

**Solução:**
```bash
# Execute o script de correção
cd /opt/edgegate
chmod +x scripts/fix-permissions.sh
./scripts/fix-permissions.sh
```

Ou manualmente:
```bash
sudo docker exec edgegate-backend chown -R vpnuser:vpnuser /app/data
sudo docker exec edgegate-backend chmod -R 755 /app/data
sudo docker compose restart backend
```

---

### 2. Erro: "failed to connect to the docker API at unix:///var/run/docker.sock"

**Causa:** O GID do grupo docker no container não coincide com o GID do docker socket no host.

**Status:** ✅ Corrigido automaticamente pelo `install.sh` (detecta o GID do host e configura `group_add`)

**Diagnóstico:**
```bash
# 1. Verificar GID do docker socket no host
stat -c '%g' /var/run/docker.sock

# 2. Verificar grupos do vpnuser no container
docker exec edgegate-backend id

# 3. Verificar se o GID do socket está nos grupos do vpnuser
docker exec edgegate-backend ls -la /var/run/docker.sock
```

**Solução (se ainda ocorrer em instalações antigas):**

Adicione o GID correto no `docker-compose.yml`:
```yaml
  backend:
    # ... outras configs ...
    group_add:
      - "988"  # Substituir pelo GID real: stat -c '%g' /var/run/docker.sock
```

Depois recrie o container:
```bash
cd /opt/edgegate
docker compose up -d backend
```

**Verificar correção:**
```bash
# Confirmar que o backend acessa a Docker API
docker exec edgegate-backend docker ps --filter name=edgegate-openvpn
```

---

### 3. Erro: "Could not read OpenVPN status file"

**Causa:** O arquivo de status está dentro do container OpenVPN e não é acessível diretamente

**Status:** ✅ Corrigido na última versão (lê via `docker exec`)

Se ainda ocorrer:
```bash
# Verificar se arquivo existe
sudo docker exec edgegate-openvpn cat /etc/openvpn/logs/status.log

# Dar permissão de leitura
sudo docker exec edgegate-openvpn chmod 644 /etc/openvpn/logs/status.log
```

---

### 4. OpenVPN não inicia

**Diagnóstico:**
```bash
# Ver logs do OpenVPN
sudo docker logs edgegate-openvpn

# Verificar se container está rodando
sudo docker ps | grep openvpn

# Verificar porta
sudo ss -tulpn | grep 1194
```

**Soluções:**
```bash
# 1. Recriar container
sudo docker compose up -d --force-recreate openvpn

# 2. Limpar volumes e recriar (CUIDADO: perde dados)
sudo docker compose down -v
sudo docker compose up -d
```

---

### 5. Regras de firewall não surtem efeito imediato (conntrack)

**Sintoma:** Ao desativar "Allow Internal Communications", a regra é removida mas ping/conexões continuam funcionando por até 30s (ICMP) ou 5 dias (TCP).

**Causa:** A tabela conntrack do kernel mantém sessões ativas que passam pela regra `ESTABLISHED` antes de consultar o `VPN_FILTER`.

**Status:** ✅ Corrigido automaticamente (flush seletivo do conntrack ao recarregar regras)

**Se ainda ocorrer em instalações antigas:**

1. Verificar se `conntrack-tools` está instalado no container:
```bash
docker exec edgegate-openvpn conntrack --version
```

2. Se não estiver, rebuild o container:
```bash
cd /opt/edgegate
docker compose up -d --build openvpn
```

3. Verificar manualmente as entradas conntrack:
```bash
# Ver entradas da sub-rede VPN
docker exec edgegate-openvpn conntrack -L -s 10.8.0.0/24

# Limpar manualmente (se necessário)
docker exec edgegate-openvpn conntrack -D -s 10.8.0.0/24
```

**Importante:** Nunca use `conntrack -F` (flush total) - isso derruba o túnel VPN e desconecta todos os clientes.

---

### 6. Management Interface não acessível (porta 7505)

**Verificar:**
```bash
# Dentro do container OpenVPN
sudo docker exec edgegate-openvpn netstat -tulpn | grep 7505

# Testar management interface
echo "status" | sudo docker exec -i edgegate-openvpn nc localhost 7505
```

**Solução:**
Verificar se `server.conf` tem a linha:
```
management 0.0.0.0 7505
```

---

## Script de Verificação Completa

Execute para verificar todo o sistema:

```bash
#!/bin/bash
echo "=== EdgeGate - Health Check ==="

echo -e "\n1. Containers:"
sudo docker ps --filter "name=vpn-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo -e "\n2. Docker socket:"
sudo docker exec edgegate-backend ls -la /var/run/docker.sock 2>&1

echo -e "\n3. Data directory permissions:"
sudo docker exec edgegate-backend ls -la /app/data 2>&1

echo -e "\n4. OpenVPN status:"
sudo docker exec edgegate-openvpn pgrep -x openvpn && echo "Running" || echo "NOT Running"

echo -e "\n5. OpenVPN management interface:"
echo "status 2" | sudo docker exec -i edgegate-openvpn nc localhost 7505 2>&1 | head -5

echo -e "\n6. Backend API:"
curl -s http://localhost/health | jq .

echo -e "\n7. Recent backend errors:"
sudo docker logs edgegate-backend --tail 20 2>&1 | grep -i error

echo -e "\n=== Health Check Complete ==="
```

---

## Logs Úteis

```bash
# Ver todos os logs
sudo docker compose logs -f

# Logs específicos
sudo docker compose logs -f backend
sudo docker compose logs -f openvpn
sudo docker compose logs -f nginx

# Logs com filtro
sudo docker compose logs backend | grep -i error
sudo docker compose logs backend | grep -i vpn
```

---

## Restart Completo

Se tudo falhar:

```bash
cd /opt/edgegate

# 1. Backup dos dados (IMPORTANTE!)
sudo docker exec edgegate-postgres pg_dump -U edgegate_admin edgegate > /tmp/vpn_backup.sql
sudo cp -r /var/lib/docker/volumes/edgegate_openvpn_data /tmp/openvpn_backup

# 2. Parar tudo
sudo docker compose down

# 3. Limpar (CUIDADO! Remove dados não salvos em volumes)
sudo docker compose down -v  # Remove volumes também

# 4. Recriar tudo
sudo docker compose up -d

# 5. Restaurar backup (se necessário)
cat /tmp/vpn_backup.sql | sudo docker exec -i edgegate-postgres psql -U edgegate_admin -d edgegate
```

---

## IPsec Site-to-Site - Troubleshooting

### 7. IPsec túnel não estabelece (IKE SA falha)

**Sintoma:** Status mostra "CONNECTING" indefinidamente ou "DOWN"

**Diagnóstico:**
```bash
# Ver logs do IPsec Agent
sudo journalctl -u ipsec-agent -f

# Ver logs do StrongSwan
sudo journalctl -u strongswan -f

# Status detalhado
ipsec statusall
```

**Causas comuns:**

**A) PSK lookup failure ("no shared key found")**
```
no shared key found for '203.0.113.10' - '198.51.100.20'
```
- Verifique se `left_id` e `right_id` estão corretos no `/etc/ipsec.secrets`
- O PSK deve usar os IPs públicos (IDs), não os IPs privados
- Formato correto:
```
203.0.113.10 198.51.100.20 : PSK "SuaChave"
198.51.100.20 203.0.113.10 : PSK "SuaChave"
```

**B) Portas UDP bloqueadas**
```bash
# Verificar se portas estão abertas
sudo ss -ulpn | grep -E '500|4500'

# Verificar UFW
sudo ufw status | grep -E '500|4500'

# Adicionar se necessário
sudo ufw allow 500/udp
sudo ufw allow 4500/udp
```

---

### 8. IPsec erro "NO_PROPOSAL_CHOSEN"

**Sintoma:** IKE SA falha com `NO_PROPOSAL_CHOSEN` ou `AUTHENTICATION_FAILED`

**Causa:** Ciphers incompatíveis entre os peers

**Diagnóstico:**
```bash
# Ver proposta enviada
sudo journalctl -u strongswan | grep -i proposal
```

**Solução:**
- Use ciphers mais compatíveis:
  - **IKE**: `aes256-sha256-modp2048` (funciona com maioria)
  - **ESP**: `aes256-sha256` (sem PFS para maior compatibilidade)

**IMPORTANTE:** Evite usar PFS (modpXXXX) no ESP se o peer remoto não suportar:
```
# Ruim (pode falhar):
esp=aes256-sha256-modp4096!

# Bom (mais compatível):
esp=aes256-sha256!
```

---

### 9. IPsec túnel UP mas sem tráfego (routing)

**Sintoma:** Status mostra "IKE_ONLY" (amarelo) ou túnel UP mas ping não funciona

**Diagnóstico:**
```bash
# Verificar políticas XFRM
sudo ip xfrm policy

# Verificar se tráfego está sendo capturado
sudo tcpdump -i any esp -n

# Verificar UFW routing
sudo ufw status | grep -i route
```

**Causas e soluções:**

**A) UFW bloqueando forwarding:**
```bash
# Adicionar regras de routing
sudo ufw route allow from 10.7.0.0/16 to 10.10.0.0/16
sudo ufw route allow from 10.10.0.0/16 to 10.7.0.0/16
```

**B) NAT interferindo no tráfego IPsec (no peer remoto):**

O tráfego é NATado ANTES de ser capturado pela política XFRM.

**Solução no peer remoto:**
```bash
# Adicionar exceção de NAT ANTES das outras regras
iptables -t nat -I POSTROUTING 1 -s <subnet_local> -d <subnet_remota> -j ACCEPT

# Exemplo:
iptables -t nat -I POSTROUTING 1 -s 10.7.0.0/16 -d 10.10.0.0/16 -j ACCEPT
```

**C) Conntrack com entradas antigas:**
```bash
# Limpar tabela conntrack
sudo conntrack -F
```

---

### 10. IPsec Agent não responde

**Sintoma:** Erro 500 ao acessar página IPsec ou comandos não executam

**Diagnóstico:**
```bash
# Verificar se agent está rodando
sudo systemctl status ipsec-agent

# Ver logs
sudo journalctl -u ipsec-agent -n 50

# Testar diretamente
curl -H "Authorization: Bearer SEU_TOKEN" http://localhost:5001/status
```

**Solução:**
```bash
# Reiniciar agent
sudo systemctl restart ipsec-agent

# Se falhar, verificar instalação
cd /opt/edgegate/docker/ipsec-agent
sudo bash install.sh
```

---

### 11. Verificação completa IPsec

```bash
#!/bin/bash
echo "=== IPsec Health Check ==="

echo -e "\n1. StrongSwan status:"
ipsec statusall 2>&1 | head -20

echo -e "\n2. IPsec Agent:"
sudo systemctl status ipsec-agent --no-pager | head -5

echo -e "\n3. UFW IPsec ports:"
sudo ufw status | grep -E '500|4500'

echo -e "\n4. XFRM policies:"
sudo ip xfrm policy | head -20

echo -e "\n5. ipsec.secrets (sem PSK):"
sudo cat /etc/ipsec.secrets | sed 's/PSK.*/PSK "***"/'

echo -e "\n6. Recent IPsec logs:"
sudo journalctl -u strongswan --no-pager -n 10

echo -e "\n=== IPsec Check Complete ==="
```

---

### 12. Recuperar ou Resetar Senha do Admin

#### Visualizar senha atual

A senha gerada durante a instalação fica armazenada no arquivo de configuração:

```bash
grep INITIAL_ADMIN_PASSWORD /opt/edgegate/config/.env
```

> **Nota:** Este valor representa a senha definida na instalação. Se você alterou a senha pela interface web, o valor no `.env` estará desatualizado.

#### Resetar senha do admin

Se você perdeu a senha ou precisa gerar uma nova:

```bash
vpnctl reset-admin
```

Este comando irá:
1. Gerar uma nova senha aleatória de 16 caracteres
2. Atualizar diretamente no banco de dados
3. Exibir a nova senha no terminal

**Exemplo de saída:**
```
Resetting admin password...

Admin password has been reset
New password: aB3dEf6hIj8kLm0n

Please save this password and change it after login!
```

#### Boas práticas

- **Guarde a senha em local seguro** (gerenciador de senhas)
- **Altere a senha após o primeiro login** pela interface web
- **Nunca compartilhe** o arquivo `.env` ou exponha em repositórios

---

## Contato

Se os problemas persistirem, colete as seguintes informações:

```bash
# 1. Versão do Docker
docker --version
docker compose version

# 2. Sistema operacional
uname -a
cat /etc/os-release

# 3. Logs completos
sudo docker compose logs > /tmp/vpn-logs.txt

# 4. Status dos containers
sudo docker ps -a > /tmp/vpn-containers.txt
```
