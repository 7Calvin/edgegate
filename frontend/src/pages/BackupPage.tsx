import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { backupsApi } from '@/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import { getApiErrorMessage } from '@/lib/apiError'
import { PageHeader } from '@/components/PageHeader'
import { Plus, Play, Trash2, Pencil, Clock, Server, CheckCircle2, XCircle, Power, PowerOff } from 'lucide-react'

interface BackupSchedule {
  id: string
  name: string
  description?: string
  is_enabled: boolean
  schedule_times: string[]
  sftp_host: string
  sftp_port: number
  sftp_username: string
  has_password: boolean
  remote_path: string
  last_run_at?: string
  last_status?: string
  last_message?: string
}

const EMPTY = {
  name: '',
  description: '',
  is_enabled: true,
  schedule_times: '',
  sftp_host: '',
  sftp_port: '22',
  sftp_username: '',
  sftp_password: '',
  remote_path: '/{name}/{hostname}-{datetime}.tar.gz',
}

export default function BackupPage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<BackupSchedule | null>(null)
  const [form, setForm] = useState({ ...EMPTY })
  const [toDelete, setToDelete] = useState<BackupSchedule | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['backups'],
    queryFn: () => backupsApi.list().then((r) => r.data as BackupSchedule[]),
  })
  const backups = data ?? []

  const openCreate = () => {
    setEditing(null)
    setForm({ ...EMPTY })
    setModalOpen(true)
  }
  const openEdit = (b: BackupSchedule) => {
    setEditing(b)
    setForm({
      name: b.name,
      description: b.description || '',
      is_enabled: b.is_enabled,
      schedule_times: (b.schedule_times || []).join(', '),
      sftp_host: b.sftp_host || '',
      sftp_port: String(b.sftp_port || 22),
      sftp_username: b.sftp_username || '',
      sftp_password: '', // blank keeps the stored one
      remote_path: b.remote_path || EMPTY.remote_path,
    })
    setModalOpen(true)
  }

  const buildPayload = () => ({
    name: form.name.trim(),
    description: form.description.trim() || null,
    is_enabled: form.is_enabled,
    schedule_times: form.schedule_times.split(',').map((t) => t.trim()).filter(Boolean),
    sftp_host: form.sftp_host.trim(),
    sftp_port: parseInt(form.sftp_port, 10) || 22,
    sftp_username: form.sftp_username.trim(),
    sftp_password: form.sftp_password,
    remote_path: form.remote_path.trim(),
  })

  const saveMutation = useMutation({
    mutationFn: () => (editing ? backupsApi.update(editing.id, buildPayload()) : backupsApi.create(buildPayload())),
    onSuccess: () => {
      toast({ title: editing ? 'Backup atualizado' : 'Backup criado' })
      queryClient.invalidateQueries({ queryKey: ['backups'] })
      setModalOpen(false)
    },
    onError: (err) => toast({ variant: 'destructive', title: getApiErrorMessage(err) }),
  })

  const toggleMutation = useMutation({
    mutationFn: (b: BackupSchedule) => backupsApi.update(b.id, { is_enabled: !b.is_enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }),
    onError: (err) => toast({ variant: 'destructive', title: getApiErrorMessage(err) }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => backupsApi.remove(id),
    onSuccess: () => {
      toast({ title: 'Backup removido' })
      queryClient.invalidateQueries({ queryKey: ['backups'] })
      setToDelete(null)
    },
    onError: (err) => toast({ variant: 'destructive', title: getApiErrorMessage(err) }),
  })

  const runNow = async (b: BackupSchedule) => {
    setRunningId(b.id)
    try {
      const res = await backupsApi.run(b.id)
      const { success, message } = res.data as { success: boolean; message: string }
      toast({
        variant: success ? 'default' : 'destructive',
        title: success ? 'Backup concluído' : 'Falha no backup',
        description: message,
      })
      queryClient.invalidateQueries({ queryKey: ['backups'] })
    } catch (err) {
      toast({ variant: 'destructive', title: getApiErrorMessage(err) })
    } finally {
      setRunningId(null)
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Backup"
        subtitle="Backups agendados enviados por SFTP (DB + PKI do OpenVPN)."
        actions={
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4 mr-2" /> Novo Backup
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary" />
        </div>
      ) : backups.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Nenhum backup agendado. Crie um para enviar backups automáticos por SFTP.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {backups.map((b) => (
            <Card key={b.id}>
              <CardContent className="flex flex-wrap items-center gap-4 py-4">
                <div className="flex-1 min-w-[200px]">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{b.name}</span>
                    {b.is_enabled ? (
                      <span className="text-xs rounded-full bg-success/15 text-success px-2 py-0.5">ativo</span>
                    ) : (
                      <span className="text-xs rounded-full bg-muted text-muted-foreground px-2 py-0.5">pausado</span>
                    )}
                  </div>
                  {b.description && <p className="text-sm text-muted-foreground">{b.description}</p>}
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" /> {(b.schedule_times || []).join(', ') || '—'}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Server className="h-3.5 w-3.5" /> SFTP {b.sftp_username}@{b.sftp_host}:{b.sftp_port}
                    </span>
                  </div>
                  {b.last_status && (
                    <div className="mt-1 flex items-center gap-1 text-xs">
                      {b.last_status === 'success' ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-destructive" />
                      )}
                      <span className="text-muted-foreground">
                        Último: {b.last_status}{b.last_message ? ` — ${b.last_message}` : ''}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="sm" title="Executar agora" disabled={runningId === b.id} onClick={() => runNow(b)}>
                    <Play className={`h-4 w-4 ${runningId === b.id ? 'animate-pulse' : ''}`} />
                  </Button>
                  <Button variant="ghost" size="sm" title={b.is_enabled ? 'Pausar' : 'Ativar'} onClick={() => toggleMutation.mutate(b)}>
                    {b.is_enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                  </Button>
                  <Button variant="ghost" size="sm" title="Editar" onClick={() => openEdit(b)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="sm" title="Excluir" className="hover:text-destructive" onClick={() => setToDelete(b)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create / Edit modal */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar backup' : 'Novo backup agendado'}</DialogTitle>
            <DialogDescription>Backup completo (DB + PKI) enviado por SFTP nos horários definidos.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
            <div className="space-y-1">
              <Label>Nome</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Backup diário" />
            </div>
            <div className="space-y-1">
              <Label>Descrição (opcional)</Label>
              <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label>Horários (HH:MM, separados por vírgula — horário do servidor)</Label>
              <Input value={form.schedule_times} onChange={(e) => setForm({ ...form, schedule_times: e.target.value })} placeholder="12:00, 17:00" className="font-mono" />
            </div>
            <div className="pt-2 border-t border-border">
              <p className="text-sm font-semibold mb-2">Destino SFTP</p>
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 space-y-1">
                  <Label>Host</Label>
                  <Input value={form.sftp_host} onChange={(e) => setForm({ ...form, sftp_host: e.target.value })} placeholder="sftp.exemplo.com" />
                </div>
                <div className="space-y-1">
                  <Label>Porta</Label>
                  <Input value={form.sftp_port} onChange={(e) => setForm({ ...form, sftp_port: e.target.value })} className="font-mono" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 mt-2">
                <div className="space-y-1">
                  <Label>Usuário</Label>
                  <Input value={form.sftp_username} onChange={(e) => setForm({ ...form, sftp_username: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Senha {editing && <span className="text-xs text-muted-foreground">(em branco = manter)</span>}</Label>
                  <Input type="password" value={form.sftp_password} onChange={(e) => setForm({ ...form, sftp_password: e.target.value })} />
                </div>
              </div>
              <div className="space-y-1 mt-2">
                <Label>Caminho remoto</Label>
                <Input value={form.remote_path} onChange={(e) => setForm({ ...form, remote_path: e.target.value })} className="font-mono text-sm" />
                <p className="text-xs text-muted-foreground">Placeholders: {'{name} {hostname} {date} {time} {datetime}'}</p>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm pt-1">
              <input type="checkbox" checked={form.is_enabled} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />
              Ativo
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)}>Cancelar</Button>
            <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !form.name.trim() || !form.sftp_host.trim() || !form.sftp_username.trim()}>
              {saveMutation.isPending ? 'Salvando…' : editing ? 'Salvar' : 'Criar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <Dialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Excluir backup</DialogTitle>
            <DialogDescription>
              Remover <span className="font-mono font-bold">{toDelete?.name}</span>? Esta ação não pode ser desfeita.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>Cancelar</Button>
            <Button variant="destructive" onClick={() => toDelete && deleteMutation.mutate(toDelete.id)} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? 'Excluindo…' : 'Excluir'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
