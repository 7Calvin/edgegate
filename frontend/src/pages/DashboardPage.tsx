import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { connectionsApi, usersApi, vpnApi, ipsecApi, proxyApi, adminApi } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PageHeader, StatTile } from '@/components/PageHeader'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { ThroughputChart } from '@/components/ThroughputChart'
import { formatBytes, formatCertificateExpiry } from '@/lib/utils'
import { cn } from '@/lib/utils'
import { formatDateTime } from '@/lib/tz'
import { Server as ServerIcon } from 'lucide-react'
import { Activity, Shield, ArrowUpDown, Download, Calendar, Lock, RefreshCw, Users, Network, KeyRound, type LucideIcon } from 'lucide-react'

type TwWindow = '1h' | '6h' | '24h' | '7d'
const TW_LABEL: Record<TwWindow, string> = { '1h': '1h', '6h': '6h', '24h': '24h', '7d': '7d' }

export default function DashboardPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.is_admin
  const queryClient = useQueryClient()
  const { info: sysInfo, update } = useSystemStatus()

  const { data: mgmtDomain } = useQuery({
    queryKey: ['management-domain'],
    queryFn: () => proxyApi.getManagementDomain().then((r) => r.data),
    enabled: isAdmin,
  })
  const { data: certInfo } = useQuery({
    queryKey: ['management-cert', mgmtDomain?.domain],
    queryFn: () => proxyApi.certificateDetails(mgmtDomain.domain).then((r: any) => r.data).catch(() => null),
    enabled: !!(isAdmin && mgmtDomain?.domain),
  })

  const { data: stats } = useQuery({ queryKey: ['connection-stats'], queryFn: () => connectionsApi.stats().then((r) => r.data), refetchInterval: 30000, enabled: isAdmin })
  const { data: userStats } = useQuery({ queryKey: ['user-stats'], queryFn: () => usersApi.stats().then((r) => r.data), enabled: isAdmin })
  const { data: vpnStatus } = useQuery({ queryKey: ['vpn-status'], queryFn: () => vpnApi.serverStatus().then((r) => r.data), refetchInterval: 30000, enabled: isAdmin })
  const { data: ipsecStatus } = useQuery({ queryKey: ['ipsec-status'], queryFn: () => ipsecApi.status().then((r) => r.data), refetchInterval: 15000, enabled: isAdmin })
  const [twWindow, setTwWindow] = useState<TwWindow>('24h')
  const { data: tpOvpn } = useQuery({ queryKey: ['throughput', twWindow, 'openvpn'], queryFn: () => connectionsApi.throughput(twWindow, 'openvpn').then((r) => r.data), refetchInterval: 60000, enabled: isAdmin })
  const { data: tpIpsec } = useQuery({ queryKey: ['throughput', twWindow, 'ipsec'], queryFn: () => connectionsApi.throughput(twWindow, 'ipsec').then((r) => r.data), refetchInterval: 60000, enabled: isAdmin })
  const { data: ldap } = useQuery({ queryKey: ['ldap-settings-summary'], queryFn: () => adminApi.getLdapSettings().then((r) => r.data).catch(() => null), enabled: isAdmin })

  const { data: myProfile } = useQuery({ queryKey: ['my-vpn-profile'], queryFn: () => vpnApi.getProfile().then((r) => r.data).catch(() => null), enabled: !isAdmin })
  const { data: myStats } = useQuery({ queryKey: ['my-connection-stats'], queryFn: () => connectionsApi.myStats().then((r) => r.data).catch(() => null), enabled: !isAdmin })
  const { data: myActiveConnection } = useQuery({ queryKey: ['my-active-connection'], queryFn: () => connectionsApi.myActive().then((r) => r.data).catch(() => null), refetchInterval: 30000, enabled: !isAdmin })

  const refreshAll = () => queryClient.invalidateQueries()

  if (isAdmin) {
    const online = vpnStatus?.is_running
    return (
      <div className="space-y-6">
        <PageHeader
          title="Centro de Operações"
          subtitle="Visão geral do sistema"
          actions={
            <Button variant="outline" size="sm" onClick={refreshAll}>
              <RefreshCw className="mr-2 h-4 w-4" /> Atualizar
            </Button>
          }
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Sessões" value={stats?.active_connections ?? 0} sub={`${stats?.total_connections ?? 0} hoje`} icon={<Activity className="h-4 w-4" />} />
          <StatTile
            label="OpenVPN"
            value={online ? 'Online' : 'Offline'}
            valueClassName={online ? 'text-success' : 'text-destructive'}
            sub={`${vpnStatus?.connected_clients ?? 0} clientes`}
            icon={<Shield className="h-4 w-4" />}
          />
          <StatTile label="Usuários" value={userStats?.total_users ?? 0} sub={`${userStats?.active_users ?? 0} ativos`} icon={<Users className="h-4 w-4" />} />
          <StatTile
            label="IPsec"
            value={`${ipsecStatus?.active_tunnels ?? 0} / ${ipsecStatus?.total_connections ?? 0}`}
            valueClassName={ipsecStatus?.active_tunnels > 0 ? 'text-success' : ''}
            sub={ipsecStatus?.strongswan_running ? 'StrongSwan ativo' : 'StrongSwan parado'}
            icon={<Lock className="h-4 w-4" />}
          />
        </div>

        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0 p-4 pb-3">
            <CardTitle className="flex items-center gap-2 text-base"><ArrowUpDown className="h-4 w-4 text-primary" /> Throughput</CardTitle>
            <div className="flex items-center gap-3">
              <div className="hidden items-center gap-4 text-xs text-muted-foreground sm:flex">
                <span className="inline-flex items-center gap-1.5"><span className="h-1 w-4 rounded-full" style={{ background: 'hsl(188 84% 53%)' }} /> saída</span>
                <span className="inline-flex items-center gap-1.5"><span className="h-1 w-4 rounded-full" style={{ background: 'hsl(255 100% 68%)' }} /> entrada</span>
              </div>
              <div className="flex items-center rounded-lg border border-border bg-secondary/40 p-0.5">
                {(['1h', '6h', '24h', '7d'] as TwWindow[]).map((w) => (
                  <button
                    key={w}
                    onClick={() => setTwWindow(w)}
                    className={cn(
                      'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                      twWindow === w ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground'
                    )}
                  >
                    {TW_LABEL[w]}
                  </button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <div className="grid gap-6 lg:grid-cols-2 lg:gap-0">
              <div className="lg:pr-6">
                <div className="mb-2 flex items-center gap-2 border-b border-border/60 pb-2 text-sm font-medium text-foreground"><Shield className="h-4 w-4 text-primary" /> OpenVPN</div>
                <ThroughputChart points={tpOvpn?.points ?? []} />
              </div>
              <div className="mt-4 border-t border-border pt-4 lg:mt-0 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
                <div className="mb-2 flex items-center gap-2 border-b border-border/60 pb-2 text-sm font-medium text-foreground"><Lock className="h-4 w-4 text-primary" /> IPsec</div>
                <ThroughputChart points={tpIpsec?.points ?? []} />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Serviços — saúde consolidada (compacto) */}
        <Card>
          <CardHeader className="p-4 pb-3">
            <CardTitle className="flex items-center gap-2 text-base"><ServerIcon className="h-4 w-4 text-primary" /> Serviços</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <ServiceChip icon={Shield} name="OpenVPN" href="/vpn" state={online ? 'ok' : 'down'} statusText={online ? `Online · ${vpnStatus?.connected_clients ?? 0}` : 'Offline'} />
              <ServiceChip icon={Lock} name="IPsec" href="/ipsec" state={ipsecStatus?.strongswan_running ? 'ok' : 'down'} statusText={ipsecStatus?.strongswan_running ? `${ipsecStatus?.active_tunnels ?? 0}/${ipsecStatus?.total_connections ?? 0} túneis` : 'Parado'} />
              <ServiceChip icon={Network} name="Firewall" href="/firewall" state="ok" statusText="Ativo" />
              <ServiceChip icon={KeyRound} name="AD / LDAP" href="/settings?tab=auth" state={ldap?.enabled ? 'ok' : 'neutral'} statusText={ldap?.enabled ? 'Ligado' : 'Local'} />
            </div>
          </CardContent>
        </Card>

        {sysInfo && (
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Servidor · Dados */}
            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-3">
                <CardTitle className="flex items-center gap-2 text-base"><ServerIcon className="h-4 w-4 text-primary" /> Servidor · Dados</CardTitle>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-xs font-medium text-success">
                    <span className="h-1.5 w-1.5 rounded-full bg-success eg-pulse" /> Online
                  </span>
                  {sysInfo.version && <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">v{sysInfo.version}</span>}
                </div>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                  <Field label="Hostname" value={sysInfo.hostname || '—'} mono />
                  <Field label="Sistema" value={sysInfo.os || '—'} />
                  <Field label="IP privado" value={sysInfo.private_ip || '—'} mono />
                  <Field label="IP público" value={sysInfo.public_ip || '—'} mono />
                  <Field
                    label="Certificado"
                    value={certInfo ? (
                      <span className={certInfo.status === 'valid' ? 'text-success' : certInfo.status === 'expiring' ? 'text-warning' : 'text-destructive'}>
                        {certInfo.status === 'valid' ? 'Válido' : certInfo.status === 'expiring' ? 'Expirando' : 'Inválido'}
                        {typeof certInfo.days_remaining === 'number' ? ` · ${certInfo.days_remaining}d` : ''}
                      </span>
                    ) : <span className="text-muted-foreground">—</span>}
                  />
                  <Field
                    label="Atualizações"
                    value={update ? (
                      update.update_available
                        ? <span className="text-warning">v{update.latest} disponível</span>
                        : <span className="text-success">Versão mais recente</span>
                    ) : <span className="text-muted-foreground">—</span>}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Servidor · Observabilidade */}
            <Card>
              <CardHeader className="p-4 pb-3">
                <CardTitle className="flex items-center gap-2 text-base"><Activity className="h-4 w-4 text-primary" /> Servidor · Observabilidade</CardTitle>
                <CardDescription className="text-xs">Uso de recursos em tempo real</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 p-4 pt-0">
                <Meter label="CPU" pct={sysInfo.cpu_pct} sub={`${sysInfo.cpu_cores ?? '?'} vCPU · load ${sysInfo.loadavg ?? '—'}`} />
                <Meter label="Memória" pct={sysInfo.mem_pct} sub={sysInfo.mem_total_kb ? `${formatBytes((sysInfo.mem_used_kb || 0) * 1024)} / ${formatBytes(sysInfo.mem_total_kb * 1024)}` : undefined} />
                <Meter label="Disco" pct={sysInfo.disk_pct} sub={sysInfo.disk_total_kb ? `${formatBytes((sysInfo.disk_used_kb || 0) * 1024)} / ${formatBytes(sysInfo.disk_total_kb * 1024)}` : undefined} />
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    )
  }

  // ---- Regular user dashboard ----
  return (
    <div className="space-y-6">
      <PageHeader title="Minha VPN" subtitle="Status da sua conexão e perfil" />

      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="flex items-center gap-2 text-base"><Activity className="h-4 w-4 text-primary" /> Status da conexão</CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {myActiveConnection ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full bg-success eg-pulse" />
                <span className="font-medium text-success">Conectado</span>
              </div>
              <div className="grid gap-2 text-sm">
                <Row label="IP da VPN" value={<span className="font-mono">{myActiveConnection.vpn_ip}</span>} />
                <Row label="Conectado desde" value={formatDateTime(myActiveConnection.connected_at)} />
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-muted-foreground/50" />
              <span className="text-muted-foreground">Desconectado</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="flex items-center gap-2 text-base"><Shield className="h-4 w-4 text-primary" /> Meu perfil VPN</CardTitle>
          <CardDescription className="text-xs">Sua configuração de VPN</CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {myProfile ? (
            <div className="space-y-4">
              {(() => {
                const certExpiry = formatCertificateExpiry(myProfile.certificate_expires_at)
                return (
                  <div className="grid gap-2 text-sm">
                    <Row label="IP atribuído" value={<span className="font-mono">{myProfile.assigned_ip}</span>} />
                    <Row label="Status" value={<span className={myProfile.is_active ? 'text-success' : 'text-destructive'}>{myProfile.is_revoked ? 'Revogado' : myProfile.is_active ? 'Ativo' : 'Inativo'}</span>} />
                    <Row
                      label={<span className="flex items-center gap-1"><Calendar className="h-3 w-3" /> Validade do certificado</span>}
                      value={<span className={certExpiry.isExpired ? 'text-destructive' : certExpiry.isExpiringSoon ? 'text-warning' : 'text-success'}>{certExpiry.text}</span>}
                    />
                    <Row label="Total de conexões" value={myProfile.total_connections} />
                    <Row label="Tráfego total" value={formatBytes(myProfile.total_bytes_sent + myProfile.total_bytes_received)} />
                  </div>
                )
              })()}
              <Button
                className="w-full"
                disabled={myProfile.is_revoked}
                onClick={() => {
                  vpnApi.downloadConfig().then((response) => {
                    const blob = new Blob([response.data], { type: 'application/x-openvpn-profile' })
                    const url = window.URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = `${user?.username || 'client'}.ovpn`
                    a.click()
                    window.URL.revokeObjectURL(url)
                  })
                }}
              >
                <Download className="mr-2 h-4 w-4" /> Baixar config .ovpn
              </Button>
            </div>
          ) : (
            <p className="text-muted-foreground">Nenhum perfil VPN configurado. Contate o administrador.</p>
          )}
        </CardContent>
      </Card>

      {myStats && (
        <Card>
          <CardHeader className="p-4 pb-3">
            <CardTitle className="flex items-center gap-2 text-base"><ArrowUpDown className="h-4 w-4 text-primary" /> Estatísticas de uso</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm p-4 pt-0">
            <Row label="Total de sessões" value={myStats.total_connections || 0} />
            <Row label="Dados enviados" value={formatBytes(myStats.total_bytes_sent || 0)} />
            <Row label="Dados recebidos" value={formatBytes(myStats.total_bytes_received || 0)} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function ServiceChip({
  icon: Icon,
  name,
  href,
  state,
  statusText,
}: {
  icon: LucideIcon
  name: string
  href?: string
  state: 'ok' | 'down' | 'neutral'
  statusText: string
}) {
  const dot = state === 'ok' ? 'bg-success' : state === 'down' ? 'bg-destructive' : 'bg-muted-foreground'
  const body = (
    <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-secondary/20 px-3 py-2 transition-colors hover:border-primary/40">
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-foreground">{name}</p>
        <p className="truncate text-[11px] text-muted-foreground">{statusText}</p>
      </div>
      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', dot, state === 'ok' && 'eg-pulse')} />
    </div>
  )
  return href ? <Link to={href} className="block">{body}</Link> : body
}

function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  )
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('font-medium text-foreground', mono && 'font-mono')}>{value}</p>
    </div>
  )
}

function Meter({ label, pct, sub }: { label: string; pct?: number | null; sub?: string }) {
  const v = typeof pct === 'number' ? Math.max(0, Math.min(100, Math.round(pct))) : null
  const color = v == null ? 'bg-muted-foreground/40' : v >= 90 ? 'bg-destructive' : v >= 75 ? 'bg-warning' : 'bg-primary'
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn('font-medium', v != null && v >= 90 ? 'text-destructive' : v != null && v >= 75 ? 'text-warning' : 'text-primary')}>{v == null ? '—' : `${v}%`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-secondary">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${v ?? 0}%` }} />
      </div>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}
