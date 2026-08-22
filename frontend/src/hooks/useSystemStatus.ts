import { useQuery } from '@tanstack/react-query'
import { systemApi, vpnApi, ipsecApi } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

export type AlertLevel = 'info' | 'warn' | 'down'
export interface SystemAlert {
  level: AlertLevel
  text: string
  href?: string
}

export interface SystemInfo {
  os?: string | null
  hostname?: string | null
  uptime_seconds?: number | null
  cpu_pct?: number | null
  cpu_cores?: number | null
  loadavg?: string | null
  mem_pct?: number | null
  mem_total_kb?: number | null
  mem_used_kb?: number | null
  disk_pct?: number | null
  disk_total_kb?: number | null
  disk_used_kb?: number | null
  public_ip?: string | null
  private_ip?: string | null
  version?: string | null
}

/**
 * Aggregates real system health for the topbar pill, the alerts bell and the
 * dashboard system card. Admin-only (the endpoints require admin).
 */
export function useSystemStatus() {
  const { user } = useAuthStore()
  const isAdmin = !!user?.is_admin

  const { data: info } = useQuery<SystemInfo>({
    queryKey: ['system-info'],
    queryFn: () => systemApi.info().then((r) => r.data),
    enabled: isAdmin,
    refetchInterval: 30000,
  })
  const { data: upd } = useQuery({
    queryKey: ['update-check'],
    queryFn: () => systemApi.checkUpdate().then((r) => r.data).catch(() => null),
    enabled: isAdmin,
    refetchInterval: 300000,
  })
  const { data: vpn } = useQuery({
    queryKey: ['vpn-status'],
    queryFn: () => vpnApi.serverStatus().then((r) => r.data).catch(() => null),
    enabled: isAdmin,
    refetchInterval: 30000,
  })
  const { data: ipsec } = useQuery({
    queryKey: ['ipsec-status'],
    queryFn: () => ipsecApi.status().then((r) => r.data).catch(() => null),
    enabled: isAdmin,
    refetchInterval: 30000,
  })

  const alerts: SystemAlert[] = []
  if (upd?.update_available) {
    alerts.push({ level: 'info', text: `Atualização ${upd.latest ? 'v' + upd.latest : 'nova'} disponível`, href: '/settings?tab=sistema' })
  }
  if (vpn && vpn.is_running === false) {
    alerts.push({ level: 'down', text: 'Servidor OpenVPN parado', href: '/vpn' })
  }
  if (ipsec?.strongswan_running === false && ipsec?.total_connections > 0) {
    alerts.push({ level: 'down', text: 'StrongSwan parado', href: '/ipsec' })
  }
  if (typeof info?.disk_pct === 'number' && info.disk_pct >= 85) {
    alerts.push({ level: 'warn', text: `Disco em ${info.disk_pct}%`, href: '/dashboard' })
  }
  if (typeof info?.mem_pct === 'number' && info.mem_pct >= 90) {
    alerts.push({ level: 'warn', text: `Memória em ${info.mem_pct}%`, href: '/dashboard' })
  }
  if (typeof info?.cpu_pct === 'number' && info.cpu_pct >= 90) {
    alerts.push({ level: 'warn', text: `CPU em ${info.cpu_pct}%`, href: '/dashboard' })
  }
  if (ipsec?.total_connections > 0 && ipsec.active_tunnels < ipsec.total_connections) {
    const down = ipsec.total_connections - ipsec.active_tunnels
    // Todos os túneis fora = down (vermelho); parcial = warn (amarelo).
    const level: AlertLevel = ipsec.active_tunnels === 0 ? 'down' : 'warn'
    alerts.push({ level, text: `${down} túnel(is) IPsec fora do ar`, href: '/ipsec' })
  }
  const onBackup = (ipsec?.connections || []).filter((c: { on_backup?: boolean | null }) => c.on_backup)
  if (onBackup.length > 0) {
    const names = onBackup.map((c: { name: string }) => c.name).join(', ')
    alerts.push({ level: 'warn', text: `IPsec no backup — link primário indisponível: ${names}`, href: '/ipsec' })
  }

  const status: 'ok' | 'warn' | 'down' =
    alerts.some((a) => a.level === 'down') ? 'down' : alerts.some((a) => a.level === 'warn') ? 'warn' : 'ok'

  return { info, alerts, status, isAdmin, update: upd }
}
