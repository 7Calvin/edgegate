import { useEffect, useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { usersApi, authApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { parseHostEntry, anyHostContainsIp } from '@/lib/cidr'
import { X, ShieldCheck, Plus, Trash2, AlertTriangle, Globe, Network } from 'lucide-react'

interface TrustedHostsTarget {
  id: string
  username: string
  allowed_source_ips?: string[]
}

interface TrustedHostsModalProps {
  user: TrustedHostsTarget
  /** True when the admin is editing their own account (lock-out risk). */
  isSelf: boolean
  onClose: () => void
  onSaved: () => void
}

export function TrustedHostsModal({ user, isSelf, onClose, onSaved }: TrustedHostsModalProps) {
  const { toast } = useToast()
  const [entries, setEntries] = useState<string[]>(user.allowed_source_ips ?? [])
  const [draft, setDraft] = useState('')
  const [clientIp, setClientIp] = useState<string | null>(null)
  const [ack, setAck] = useState(false)

  // Best-effort: ask the server which IP it sees us from, to power the
  // anti-lockout hint. Degrades silently if the endpoint isn't available yet.
  useEffect(() => {
    let cancelled = false
    authApi
      .whoami()
      .then((res) => { if (!cancelled) setClientIp(res.data.client_ip) })
      .catch(() => { if (!cancelled) setClientIp(null) })
    return () => { cancelled = true }
  }, [])

  const draftValid = draft.trim() === '' ? null : parseHostEntry(draft) !== null
  const isRestricted = entries.length > 0

  // Would saving this list lock the current admin out of their own account?
  const wouldLockOut = useMemo(
    () => isSelf && isRestricted && clientIp !== null && !anyHostContainsIp(entries, clientIp),
    [isSelf, isRestricted, clientIp, entries],
  )

  const myIpAlreadyCovered =
    clientIp !== null && isRestricted && anyHostContainsIp(entries, clientIp)

  const addEntry = () => {
    const parsed = parseHostEntry(draft)
    if (!parsed) {
      toast({ variant: 'destructive', title: 'Endereço inválido', description: 'Use um IP ou CIDR válido (ex: 203.0.113.10 ou 10.0.0.0/24).' })
      return
    }
    if (entries.includes(parsed.normalized) || entries.includes(parsed.raw)) {
      toast({ title: 'Esse host já está na lista' })
      setDraft('')
      return
    }
    setEntries([...entries, parsed.normalized])
    setDraft('')
  }

  const addMyIp = () => {
    if (!clientIp) return
    const parsed = parseHostEntry(clientIp)
    const normalized = parsed ? parsed.normalized : clientIp
    if (entries.includes(normalized)) return
    setEntries([...entries, normalized])
  }

  const removeEntry = (value: string) => setEntries(entries.filter((e) => e !== value))

  const saveMutation = useMutation({
    mutationFn: () => usersApi.updateTrustedHosts(user.id, entries),
    onSuccess: () => {
      toast({ title: 'Trusted Hosts atualizados', description: isRestricted ? `${entries.length} host(s) permitido(s)` : 'Sem restrição de IP' })
      onSaved()
      onClose()
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string | { msg: string }[]; message?: string } } }
      let message = 'Erro desconhecido'
      const detail = err.response?.data?.detail ?? err.response?.data?.message
      if (Array.isArray(detail)) message = detail.map((e) => e.msg).join('; ')
      else if (detail) message = String(detail)
      toast({ variant: 'destructive', title: 'Falha ao salvar Trusted Hosts', description: message })
    },
  })

  const saveDisabled = saveMutation.isPending || (wouldLockOut && !ack)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-background rounded-lg shadow-xl w-full max-w-lg p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <h2 className="text-xl font-bold">Trusted Hosts</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <p className="text-sm text-muted-foreground">
          Restringe de quais IPs de origem <span className="font-medium text-foreground">{user.username}</span> pode
          autenticar no painel e via API. Aceita IP ou CIDR (IPv4/IPv6).
        </p>

        {/* Add entry */}
        <div className="space-y-2">
          <Label htmlFor="th-input">Adicionar host permitido</Label>
          <div className="flex gap-2">
            <Input
              id="th-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addEntry() } }}
              placeholder="203.0.113.10  ou  10.0.0.0/24"
              className={`font-mono ${draftValid === false ? 'border-destructive focus-visible:ring-destructive' : ''}`}
            />
            <Button type="button" onClick={addEntry} disabled={draftValid !== true}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {draftValid === false && (
            <p className="text-xs text-destructive">Formato inválido. Ex: 203.0.113.10, 10.0.0.0/24, 2001:db8::/48</p>
          )}
          {clientIp && (
            <button
              type="button"
              onClick={addMyIp}
              disabled={myIpAlreadyCovered}
              className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline disabled:opacity-50 disabled:no-underline"
            >
              <Globe className="h-3 w-3" />
              {myIpAlreadyCovered ? `Seu IP atual (${clientIp}) já está coberto` : `Adicionar meu IP atual (${clientIp})`}
            </button>
          )}
        </div>

        {/* Current list */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Hosts permitidos</Label>
            <span className="text-xs text-muted-foreground">{entries.length} entrada(s)</span>
          </div>
          {entries.length === 0 ? (
            <div className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
              <Network className="mx-auto mb-1 h-4 w-4" />
              Lista vazia — <span className="font-medium text-foreground">sem restrição</span> (qualquer IP pode acessar).
            </div>
          ) : (
            <ul className="max-h-48 space-y-1 overflow-y-auto">
              {entries.map((entry) => (
                <li key={entry} className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-1.5">
                  <span className="font-mono text-sm">{entry}</span>
                  <button
                    type="button"
                    onClick={() => removeEntry(entry)}
                    className="text-muted-foreground hover:text-destructive"
                    title="Remover"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Anti-lockout warning */}
        {wouldLockOut && (
          <div className="space-y-2 rounded-md border border-destructive/40 bg-destructive/10 p-3">
            <div className="flex items-start gap-2 text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="text-sm">
                <p className="font-medium">Você vai se bloquear.</p>
                <p className="text-destructive/90">
                  Seu IP atual ({clientIp}) não está coberto por nenhum host da lista. Ao salvar, você perderá o
                  acesso ao painel. A recuperação exige o CLI local no servidor (<span className="font-mono">vpnctl</span>).
                </p>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-destructive">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-4 w-4" />
              Entendo o risco e quero salvar mesmo assim
            </label>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={() => saveMutation.mutate()} disabled={saveDisabled}>
            {saveMutation.isPending ? 'Salvando...' : 'Salvar'}
          </Button>
        </div>
      </div>
    </div>
  )
}
