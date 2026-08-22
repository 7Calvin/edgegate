import { useEffect, useRef, useState } from 'react'
import { systemApi, type UpdateStatus } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import {
  RefreshCw,
  Download,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Server,
  Database,
  ShieldCheck,
} from 'lucide-react'

interface VersionInfo {
  current: string | null
  git_sha?: string | null
  build_date?: string | null
}

interface LatestInfo {
  latest: string | null
  current_sha?: string
  update_available: boolean
  target?: string
  error?: string
}

// Poll the host update-agent directly (via Traefik). Resilient to the backend
// and frontend restarting mid-update — a failed poll just means "not back yet".
const POLL_MS = 2000
const RUNNING_STATES = ['running']

// Compare version strings like "v1.4.3" / "1.4.3". Returns <0, 0, >0.
function cmpVer(a: string, b: string): number {
  const norm = (s: string) => s.replace(/^v/, '').split('.').map((n) => parseInt(n, 10) || 0)
  const pa = norm(a)
  const pb = norm(b)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0)
    if (d !== 0) return d
  }
  return 0
}

export default function SystemUpdateCard() {
  const { toast } = useToast()
  const [version, setVersion] = useState<VersionInfo | null>(null)
  const [latest, setLatest] = useState<LatestInfo | null>(null)
  const [checking, setChecking] = useState(false)
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [polling, setPolling] = useState(false)
  // Which confirmation modal is open (replaces the native window.confirm()).
  const [confirm, setConfirm] = useState<null | 'update' | 'regen'>(null)
  // Available version tags + the one picked in the specific-version selector.
  const [versions, setVersions] = useState<string[]>([])
  const [selectedRef, setSelectedRef] = useState<string>('')
  // The ref the pending confirmation will install (null => default: latest).
  const [targetRef, setTargetRef] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    systemApi.version().then((r) => setVersion(r.data)).catch(() => {})
    // Best-effort update check on mount (silent).
    systemApi.checkUpdate().then((r) => setLatest(r.data)).catch(() => {})
    // Available tags for the specific-version / rollback picker (silent).
    systemApi.listVersions().then((r) => setVersions(r.data?.tags ?? [])).catch(() => {})
  }, [])

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    setPolling(false)
  }

  // Poll the agent while an update is in flight.
  useEffect(() => {
    if (!polling) return
    let missed = 0
    pollRef.current = setInterval(async () => {
      const s = await systemApi.agentStatus()
      if (!s) {
        // Backend/frontend restart window — keep waiting, don't give up.
        missed += 1
        setStatus((prev) =>
          prev ? { ...prev, message: 'Reiniciando serviços… aguarde' } : prev
        )
        return
      }
      missed = 0
      setStatus(s)
      if (!RUNNING_STATES.includes(s.state)) {
        stopPolling()
        if (s.state === 'done') {
          toast({ title: 'Atualização concluída', description: s.message })
          setTimeout(() => window.location.reload(), 3000)
        } else if (s.state === 'rolled_back') {
          toast({
            title: 'Rollback automático',
            description: 'A atualização falhou e o sistema voltou à versão anterior.',
            variant: 'destructive',
          })
        } else if (s.state === 'failed') {
          toast({
            title: 'Falha na atualização',
            description: s.error || s.message,
            variant: 'destructive',
          })
        }
      }
    }, POLL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polling])

  const handleCheck = async () => {
    setChecking(true)
    try {
      const r = await systemApi.checkUpdate()
      setLatest(r.data)
      if (r.data?.update_available) {
        toast({ title: 'Atualização disponível', description: `Nova versão: ${r.data.latest ?? r.data.target}` })
      } else {
        toast({ title: 'Sistema atualizado', description: 'Você já está na versão mais recente.' })
      }
    } catch (e: any) {
      toast({
        title: 'Não foi possível verificar',
        description: e?.response?.data?.detail || 'Update-agent indisponível.',
        variant: 'destructive',
      })
    } finally {
      setChecking(false)
    }
  }

  const runUpdate = async () => {
    setConfirm(null)
    try {
      await systemApi.startUpdate({ ref: targetRef || undefined, backup: true, run_migrations: true })
      setStatus({ state: 'running', pct: 1, message: 'Iniciando atualização…' })
      setPolling(true)
    } catch (e: any) {
      toast({
        title: 'Não foi possível iniciar',
        description: e?.response?.data?.detail || 'Verifique se o update-agent está ativo.',
        variant: 'destructive',
      })
    }
  }

  const runRegenOpenvpn = async () => {
    setConfirm(null)
    try {
      await systemApi.regenerateOpenvpnConfig()
      toast({ title: 'OpenVPN', description: 'Configuração regenerada; PKI preservado.' })
    } catch (e: any) {
      toast({
        title: 'Falha ao regenerar',
        description: e?.response?.data?.detail || 'Erro no update-agent.',
        variant: 'destructive',
      })
    }
  }

  const updateAvailable = latest?.update_available
  const running = polling || status?.state === 'running'

  const targetVersion = latest?.latest ?? latest?.target
  // What the pending confirmation will install, and whether it's a rollback.
  const confirmTarget = targetRef ?? (updateAvailable ? targetVersion : null)
  const confirmIsRollback = !!(
    targetRef && version?.current && cmpVer(targetRef, `v${version.current}`) < 0
  )

  return (
    <>
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Server className="h-5 w-5" />
          Sistema & Atualizações
        </CardTitle>
        <CardDescription>
          Versão atual:{' '}
          <span className="font-mono font-medium">
            v{version?.current ?? '—'}
          </span>
          {version?.git_sha && (
            <span className="text-muted-foreground"> ({version.git_sha})</span>
          )}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Update availability banner */}
        {!running && latest && (
          <div
            className={
              'flex items-center gap-2 rounded-md border p-3 text-sm ' +
              (updateAvailable
                ? 'border-amber-500/40 bg-amber-500/10'
                : 'border-emerald-500/40 bg-emerald-500/10')
            }
          >
            {updateAvailable ? (
              <>
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <span>
                  Atualização disponível:{' '}
                  <span className="font-mono font-medium">{latest.latest ?? latest.target}</span>
                </span>
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                <span>Você está na versão mais recente.</span>
              </>
            )}
          </div>
        )}

        {/* Progress (while running / after finish) */}
        {status && (running || status.state !== 'idle') && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{status.message}</span>
              <span className="text-muted-foreground">{status.pct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={
                  'h-full transition-all duration-500 ' +
                  (status.state === 'failed'
                    ? 'bg-destructive'
                    : status.state === 'rolled_back'
                    ? 'bg-amber-500'
                    : status.state === 'done'
                    ? 'bg-emerald-500'
                    : 'bg-primary')
                }
                style={{ width: `${Math.min(100, Math.max(0, status.pct))}%` }}
              />
            </div>
            {status.error && (
              <p className="text-sm text-destructive">{status.error}</p>
            )}
            {status.log_tail && status.log_tail.length > 0 && (
              <pre className="max-h-48 overflow-auto rounded-md bg-muted/50 p-2 text-xs leading-relaxed">
                {status.log_tail.join('')}
              </pre>
            )}
          </div>
        )}

        {/* Update is always safe: automatic backup + migrations + rollback */}
        {!running && (
          <p className="rounded-lg border border-border bg-secondary/30 px-3 py-2 text-xs text-muted-foreground">
            A atualização faz <span className="text-foreground">backup automático</span> (banco + PKI do OpenVPN) e aplica as{' '}
            <span className="text-foreground">migrações do banco</span> antes de concluir. Se algo falhar, faz <span className="text-foreground">rollback automático</span>.
          </p>
        )}

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={handleCheck} disabled={checking || running} className="gap-2">
            <RefreshCw className={'h-4 w-4 ' + (checking ? 'animate-spin' : '')} />
            Verificar atualizações
          </Button>
          <Button onClick={() => { setTargetRef(null); setConfirm('update') }} disabled={running} className="gap-2">
            <Download className="h-4 w-4" />
            {running ? 'Atualizando…' : 'Atualizar agora'}
          </Button>
          <Button variant="ghost" onClick={() => setConfirm('regen')} disabled={running} className="gap-2">
            <RotateCcw className="h-4 w-4" />
            Regenerar config OpenVPN
          </Button>
        </div>

        {/* Specific version / rollback picker */}
        {!running && versions.length > 0 && (
          <div className="space-y-2 rounded-lg border border-border bg-secondary/20 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <RotateCcw className="h-4 w-4 text-muted-foreground" />
              Instalar versão específica / rollback
            </div>
            <p className="text-xs text-muted-foreground">
              Instala uma versão exata. Versões anteriores à atual fazem{' '}
              <span className="text-foreground">rollback</span> — o schema do banco é
              preservado (sem downgrade destrutivo) e o backup pré-update fica disponível.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                value={selectedRef}
                onChange={(e) => setSelectedRef(e.target.value)}
              >
                <option value="">Selecione uma versão…</option>
                {versions.map((t) => {
                  const rel = version?.current ? cmpVer(t, `v${version.current}`) : 1
                  const label = rel === 0 ? ' (atual)' : rel < 0 ? ' — rollback' : ' — upgrade'
                  return (
                    <option key={t} value={t} disabled={rel === 0}>
                      {t}{label}
                    </option>
                  )
                })}
              </select>
              <Button
                variant="outline"
                disabled={!selectedRef}
                onClick={() => { setTargetRef(selectedRef); setConfirm('update') }}
                className="gap-2"
              >
                <Download className="h-4 w-4" />
                Instalar esta versão
              </Button>
            </div>
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          A atualização preserva os certificados/PKI do OpenVPN e não derruba
          banco, cache ou proxy. Em caso de falha no health-check, o sistema faz
          rollback automático para a versão anterior.
        </p>
      </CardContent>
    </Card>

    {/* Update confirmation modal (replaces the native confirm dialog) */}
    <Dialog open={confirm === 'update'} onOpenChange={(o) => !o && setConfirm(null)}>
      <DialogContent onClose={() => setConfirm(null)}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {confirmIsRollback ? <RotateCcw className="h-5 w-5 text-amber-500" /> : <Download className="h-5 w-5 text-primary" />}
            {confirmIsRollback ? 'Reverter o sistema' : 'Atualizar o sistema'}
          </DialogTitle>
          <DialogDescription>
            {confirmTarget ? (
              <>{confirmIsRollback ? 'Reverter' : 'Atualizar'} da <span className="font-mono font-medium text-foreground">v{version?.current ?? '—'}</span> para a{' '}
              <span className="font-mono font-medium text-foreground">{confirmTarget}</span>. O que vai acontecer:</>
            ) : (
              <>Reconstruir os serviços na versão mais recente disponível. O que vai acontecer:</>
            )}
          </DialogDescription>
        </DialogHeader>

        <ul className="my-2 space-y-2.5 text-sm">
          <li className="flex items-start gap-2.5">
            <Database className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span><span className="font-medium text-foreground">Backup automático</span> do banco e da PKI do OpenVPN antes de tudo.</span>
          </li>
          {confirmIsRollback && (
            <li className="flex items-start gap-2.5">
              <Database className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <span>Rollback: o <span className="font-medium text-foreground">schema do banco é preservado</span> (sem downgrade destrutivo). As migrações são puladas; o backup pré-update fica disponível para restauração manual, se necessário.</span>
            </li>
          )}
          <li className="flex items-start gap-2.5">
            <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>Serviços <span className="font-medium text-foreground">reconstruídos</span> e <span className="font-medium text-foreground">migrações</span> do banco aplicadas — pode haver uma breve indisponibilidade.</span>
          </li>
          <li className="flex items-start gap-2.5">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            <span><span className="font-medium text-foreground">Rollback automático</span> se o health-check falhar. Certificados/PKI são preservados.</span>
          </li>
        </ul>

        <DialogFooter>
          <Button variant="outline" onClick={() => setConfirm(null)}>Cancelar</Button>
          <Button onClick={runUpdate} className="gap-2">
            {confirmIsRollback ? <RotateCcw className="h-4 w-4" /> : <Download className="h-4 w-4" />}
            {confirmIsRollback ? 'Reverter agora' : 'Atualizar agora'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Regenerate OpenVPN config confirmation */}
    <Dialog open={confirm === 'regen'} onOpenChange={(o) => !o && setConfirm(null)}>
      <DialogContent onClose={() => setConfirm(null)}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5 text-primary" />
            Regenerar config do OpenVPN
          </DialogTitle>
          <DialogDescription>
            Recria o <span className="font-mono text-foreground">server.conf</span> a partir do template.
            Isso <span className="font-medium text-foreground">descarta edições manuais</span> do arquivo.
            Os certificados/PKI são preservados.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setConfirm(null)}>Cancelar</Button>
          <Button onClick={runRegenOpenvpn} className="gap-2">
            <RotateCcw className="h-4 w-4" />
            Regenerar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  )
}
