import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '@/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/PageHeader'
import { formatDateTime } from '@/lib/tz'
import { cn } from '@/lib/utils'
import { Search, Download, LogIn, Shield, Settings2, Server, UserPlus, RefreshCw, type LucideIcon } from 'lucide-react'

interface AuditRow {
  id: string
  created_at: string | null
  username: string | null
  action: string
  resource_type: string | null
  ip_address: string | null
  severity: string
}

const CATEGORIES: { key: string; label: string }[] = [
  { key: '', label: 'Todas' },
  { key: 'auth', label: 'Autenticação' },
  { key: 'users', label: 'Usuários' },
  { key: 'vpn', label: 'OpenVPN' },
  { key: 'ipsec', label: 'IPsec' },
  { key: 'config', label: 'Configuração' },
  { key: 'system', label: 'Sistema' },
]

const SEVERITIES: { key: string; label: string }[] = [
  { key: '', label: 'Todas severidades' },
  { key: 'info', label: 'Info' },
  { key: 'warning', label: 'Atenção' },
  { key: 'error', label: 'Erro' },
  { key: 'critical', label: 'Crítico' },
]

const catMeta: Record<string, { label: string; icon: LucideIcon }> = {
  auth: { label: 'Autenticação', icon: LogIn },
  users: { label: 'Usuários', icon: UserPlus },
  vpn: { label: 'OpenVPN', icon: Shield },
  ipsec: { label: 'IPsec', icon: Shield },
  config: { label: 'Configuração', icon: Settings2 },
  system: { label: 'Sistema', icon: Server },
}

const sevMeta: Record<string, { label: string; cls: string; dot: string }> = {
  debug: { label: 'Debug', cls: 'text-muted-foreground', dot: 'bg-muted-foreground' },
  info: { label: 'Info', cls: 'text-muted-foreground', dot: 'bg-muted-foreground' },
  warning: { label: 'Atenção', cls: 'text-warning', dot: 'bg-warning' },
  error: { label: 'Erro', cls: 'text-destructive', dot: 'bg-destructive' },
  critical: { label: 'Crítico', cls: 'text-destructive', dot: 'bg-destructive' },
}

const PAGE_SIZE = 50

export default function AuditPage() {
  const [query, setQuery] = useState('')
  const [cat, setCat] = useState('')
  const [sev, setSev] = useState('')
  const [page, setPage] = useState(1)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['audit-logs', page, cat, sev, query],
    queryFn: () => adminApi.auditLogs({
      page, page_size: PAGE_SIZE,
      category: cat || undefined, severity: sev || undefined, search: query || undefined,
    }).then((r) => r.data),
    refetchInterval: 30000,
  })

  const rows: AuditRow[] = data?.items || []
  const total: number = data?.total || 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const resetTo = (fn: () => void) => { fn(); setPage(1) }
  const selectCls = 'h-9 rounded-lg border border-border bg-secondary/40 px-3 text-sm text-foreground focus:outline-none focus:border-primary/50'

  const exportCsv = () => {
    const header = ['data_hora', 'usuario', 'ip', 'categoria', 'acao', 'severidade']
    const lines = rows.map((r) => [
      formatDateTime(r.created_at, { withSeconds: true }), r.username || '', r.ip_address || '',
      r.resource_type || '', r.action, r.severity,
    ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
    const blob = new Blob([[header.join(','), ...lines].join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'auditoria.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Auditoria"
        subtitle="Registro de eventos do sistema"
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => refetch()}><RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} /></Button>
            <Button variant="outline" size="sm" onClick={exportCsv} disabled={!rows.length}><Download className="mr-2 h-4 w-4" /> Exportar CSV</Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => resetTo(() => setQuery(e.target.value))} placeholder="Buscar por ação ou usuário..." className="pl-9" />
        </div>
        <select value={cat} onChange={(e) => resetTo(() => setCat(e.target.value))} className={selectCls}>
          {CATEGORIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select value={sev} onChange={(e) => resetTo(() => setSev(e.target.value))} className={selectCls}>
          {SEVERITIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-3 font-medium">Data / hora</th>
                  <th className="px-4 py-3 font-medium">Usuário</th>
                  <th className="px-4 py-3 font-medium">IP</th>
                  <th className="px-4 py-3 font-medium">Categoria</th>
                  <th className="px-4 py-3 font-medium">Ação</th>
                  <th className="px-4 py-3 font-medium">Severidade</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const s = sevMeta[r.severity] || sevMeta.info
                  const cm = (r.resource_type && catMeta[r.resource_type]) || null
                  return (
                    <tr key={r.id} className="border-b border-border/60 last:border-0 hover:bg-accent/20">
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted-foreground">{formatDateTime(r.created_at, { withSeconds: true })}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-foreground">{r.username || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted-foreground">{r.ip_address || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                          {cm && <cm.icon className="h-3.5 w-3.5" />}
                          {cm?.label || r.resource_type || '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-foreground">{r.action}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className={cn('inline-flex items-center gap-1.5 text-xs font-medium', s.cls)}>
                          <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
                          {s.label}
                        </span>
                      </td>
                    </tr>
                  )
                })}
                {rows.length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">{isFetching ? 'Carregando...' : 'Nenhum evento encontrado'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-muted-foreground">
            <span>{total} evento(s) · página {page} de {pages}</span>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>Anterior</Button>
              <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>Próxima</Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
