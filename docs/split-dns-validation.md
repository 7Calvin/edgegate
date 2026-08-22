# Split-DNS — validação pendente (OpenVPN Connect vs `DOMAIN-ROUTE`)

Status: **a validar quando alguém for usar split-DNS com um domínio real.**

## O que é

O split-DNS permite, em **split-tunnel** (Redirect Gateway desligado), resolver
**apenas domínios específicos** por um DNS interno através do túnel, mantendo a
internet e o DNS do cliente para todo o resto.

Campos na config da VPN (painel):

- `internal_dns_server` — IP do DNS interno (precisa ser alcançável pelo túnel;
  ex. dentro da rede NAT `10.48.0.0/16`).
- `split_dns_domains` — lista de domínios (ex. `corp.example`).

O backend gera, no `server.conf` e no perfil `.ovpn`:

```
# split-tunnel + split-DNS configurado
push "route <internal_dns> 255.255.255.255"
push "dhcp-option DNS <internal_dns>"
push "dhcp-option DOMAIN <primeiro_dominio>"
push "dhcp-option DOMAIN-ROUTE <dominio>"   # um por domínio
```

O `DOMAIN-ROUTE` é o que faz o **split de DNS**: no Windows ele cria uma regra
**NRPT** dizendo "nomes sob `<dominio>` vão para o DNS da VPN; o resto usa o DNS
normal do cliente".

## A incerteza

`dhcp-option DOMAIN-ROUTE` é **bem suportado no cliente OpenVPN community**
(openvpn-gui + tap-windows/wintun + OpenVPN Interactive Service, 2.5.1+), que
aplica a regra NRPT.

O cliente em uso nos testes é o **OpenVPN Connect** (tem o "DCO Adapter" —
Data Channel Offload). O OpenVPN Connect faz o próprio gerenciamento de DNS e
**pode não honrar `DOMAIN-ROUTE`** da mesma forma (pode ignorar, ou aplicar o
DNS a todos os nomes em vez de só ao domínio). Isso **não foi validado** ainda.

## Como validar (quando precisar)

1. No painel, com **Redirect Gateway desligado**, preencher `internal_dns_server`
   (um DNS interno que resolva o domínio, alcançável pelo túnel) e adicionar o
   domínio em `split_dns_domains`. Salvar.
2. Re-baixar o `.ovpn` e reimportar no cliente. Reconectar.
3. No cliente Windows:
   ```
   nslookup host.<dominio>        # deve resolver pelo DNS interno (via túnel)
   nslookup google.com            # deve resolver pelo DNS local do cliente
   ipconfig /all                  # conferir DNS/《NRPT》no adaptador
   Get-DnsClientNrptPolicy        # (PowerShell) lista as regras NRPT ativas
   ```
4. Confirmar que **só** o domínio interno vai pelo DNS do túnel e o resto
   continua no DNS local.

## Se o OpenVPN Connect NÃO respeitar `DOMAIN-ROUTE`

Opções de contorno, em ordem de preferência:

1. **Usar o cliente community** (openvpn-gui) para os casos que precisam de
   split-DNS — ele aplica NRPT corretamente.
2. **Aceitar split-DNS "amplo"**: empurrar o DNS interno como único resolvedor em
   split-tunnel (sem `DOMAIN-ROUTE`). O DNS interno precisa então resolver
   *também* nomes públicos (forwarders), senão a navegação geral quebra. Menos
   ideal, mas funciona se o DNS interno tiver forwarders.
3. **Configurar o split-DNS no lado do cliente/gerenciamento do OpenVPN Connect**
   (perfis gerenciados do Connect têm mecanismo próprio), fora do `dhcp-option`.

## Referências

- OpenVPN `--dhcp-option DOMAIN-ROUTE` (Windows NRPT), community 2.5.1+.
- OpenVPN 2.6 `--dns` (`resolve-domains`) — alternativa mais nova ao
  `dhcp-option DNS/DOMAIN-ROUTE`, se migrarmos a geração de config no futuro.
