import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ipsecApi } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/hooks/use-toast'
import { PageHeader } from '@/components/PageHeader'
import {
  Shield,
  ShieldOff,
  Trash2,
  Plus,
  Play,
  Square,
  RotateCcw,
  Network,
  Server,
  RefreshCw,
  Eye,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertCircle,
  Pencil,
  FileText,
  Terminal,
  Zap,
  Undo2,
  ArrowLeftRight,
  MoreVertical,
  Download,
  Copy,
} from 'lucide-react'
import type { IPsecConnection, IPsecStatus, IPsecConnectionCreate } from '@/types'

interface ConnectionForm {
  name: string
  description: string
  left_ip: string
  left_subnet: string
  left_id: string
  right_ip: string
  right_ip_backup: string
  right_subnet: string
  right_id: string
  auth_method: string
  psk: string
  ike_version: string
  ike_cipher: string
  ike_lifetime: string
  esp_cipher: string
  key_lifetime: string
  auto_start: boolean
  dpd_action: string
  is_enabled: boolean
}

interface ServerInfo {
  private_ip: string | null
  public_ip: string | null
  local_subnet: string | null
  interface: string | null
}

const IKE_VERSION_OPTIONS = [
  { value: 'ikev2', label: 'IKEv2 (Recomendado)' },
  { value: 'ikev1', label: 'IKEv1 (Legado)' },
]

const DPD_ACTION_OPTIONS = [
  { value: 'restart', label: 'Restart - Reconectar em caso de falha' },
  { value: 'clear', label: 'Clear - Remover SA em caso de falha' },
  { value: 'hold', label: 'Hold - Continuar tentando' },
  { value: 'none', label: 'None - Desabilitar DPD' },
]

const IKE_CIPHER_PRESETS = [
  { value: 'aes256-sha256-modp2048', label: 'AES-256 SHA-256 DH-2048 (Recomendado)' },
  { value: 'aes256-sha256-modp4096', label: 'AES-256 SHA-256 DH-4096 (Forte)' },
  { value: 'aes128-sha256-modp2048', label: 'AES-128 SHA-256 DH-2048 (Rápido)' },
  { value: 'aes256-sha512-modp4096', label: 'AES-256 SHA-512 DH-4096 (Muito Forte)' },
]

const ESP_CIPHER_PRESETS = [
  { value: 'aes256-sha256', label: 'AES-256 SHA-256 (Recomendado - Sem PFS)' },
  { value: 'aes256-sha256-modp2048', label: 'AES-256 SHA-256 DH-2048 (Com PFS)' },
  { value: 'aes128-sha256', label: 'AES-128 SHA-256 (Rápido - Sem PFS)' },
  { value: 'aes256-sha1', label: 'AES-256 SHA-1 (Compatível com Legado)' },
]

const createInitialForm = (serverInfo?: ServerInfo): ConnectionForm => ({
  name: '',
  description: '',
  left_ip: serverInfo?.private_ip || '',
  left_subnet: serverInfo?.local_subnet || '',
  left_id: serverInfo?.public_ip || '',
  right_ip: '',
  right_ip_backup: '',
  right_subnet: '',
  right_id: '',
  auth_method: 'psk',
  psk: '',
  ike_version: 'ikev2',
  ike_cipher: 'aes256-sha256-modp2048',
  ike_lifetime: '8h',
  esp_cipher: 'aes256-sha256',
  key_lifetime: '1h',
  auto_start: true,
  dpd_action: 'restart',
  is_enabled: true,
})

export default function IPsecPage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [previewConn, setPreviewConn] = useState<IPsecConnection | null>(null)
  const [deleteConn, setDeleteConn] = useState<IPsecConnection | null>(null)
  const [deleteText, setDeleteText] = useState('')
  const [exportConn, setExportConn] = useState<IPsecConnection | null>(null)
  const [exportForm, setExportForm] = useState({
    target: 'fortigate', fortios: '7.4', wan_pri: '', wan_bak: '',
    lan_if: '', sla_src: '', localid_pri: '', localid_bak: '',
    base: '', client_lan: '',
  })
  const [isStatusModalOpen, setIsStatusModalOpen] = useState(false)
  const [isLogsModalOpen, setIsLogsModalOpen] = useState(false)
  const [logsConnectionName, setLogsConnectionName] = useState<string | null>(null)
  const [formData, setFormData] = useState<ConnectionForm>(createInitialForm())
  const [editingConnection, setEditingConnection] = useState<IPsecConnection | null>(null)
  // Backup/failover toggle for the create/edit form. When off, the backup IP field is
  // hidden and right_ip_backup is cleared — that empty value is the single balizador the
  // backend (and the download modal) use to switch between single-link and failover.
  const [showBackup, setShowBackup] = useState(false)

  // Queries
  const { data: connectionsData, isLoading } = useQuery({
    queryKey: ['ipsec-connections'],
    queryFn: () => ipsecApi.list().then((res) => res.data),
  })

  const { data: status, refetch: refetchStatus } = useQuery<IPsecStatus>({
    queryKey: ['ipsec-status'],
    queryFn: () => ipsecApi.status().then((res) => res.data),
    refetchInterval: 10000,
  })

  const { data: connConfig, isLoading: connConfigLoading } = useQuery({
    queryKey: ['ipsec-conn-config', previewConn?.id],
    queryFn: () => ipsecApi.connectionConfig(previewConn!.id).then((res) => res.data as string),
    enabled: !!previewConn,
  })

  const { data: exportText, isFetching: exportLoading } = useQuery({
    queryKey: ['ipsec-export', exportConn?.id, exportForm],
    queryFn: () => ipsecApi.exportConfig(exportConn!.id, {
      target: exportForm.target,
      fortios: exportForm.fortios,
      wan_pri: exportForm.wan_pri || '<WAN_PRI>',
      wan_bak: exportForm.wan_bak || '<WAN_BAK>',
      lan_if: exportForm.lan_if || '<LAN_IF>',
      sla_src: exportForm.sla_src || '<SLA_SRC>',
      localid_pri: exportForm.localid_pri,
      localid_bak: exportForm.localid_bak,
      base: exportForm.base,
      client_lan: exportForm.client_lan || '',
    }).then((res) => res.data as string),
    enabled: !!exportConn,
  })

  const downloadExport = () => {
    if (!exportConn || !exportText) return
    const isFg = exportForm.target === 'fortigate'
    const fname = isFg ? `${exportConn.name}_fortigate.conf` : `${exportConn.name}_ipsec-params.txt`
    const blob = new Blob([exportText], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = fname
    document.body.appendChild(a)
    a.click()
    a.remove()
    toast({ title: `Baixado ${fname}` })
  }

  // Copy helper with a fallback for insecure contexts. navigator.clipboard only exists
  // over HTTPS/localhost; on homolog accessed by http://<ip> it's undefined, so the old
  // `navigator.clipboard?.writeText()` silently no-op'd while still toasting "copiada".
  // Fall back to a hidden <textarea> + execCommand, and only toast success if it worked.
  const copyText = async (text: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
      } else {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.top = '-1000px'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        const ok = document.execCommand('copy')
        ta.remove()
        if (!ok) throw new Error('execCommand copy returned false')
      }
      toast({ title: 'Config copiada' })
    } catch {
      toast({
        variant: 'destructive',
        title: 'Não foi possível copiar',
        description: 'Selecione o texto e copie manualmente (Ctrl+C).',
      })
    }
  }

  const { data: serverInfo } = useQuery<ServerInfo>({
    queryKey: ['ipsec-server-info'],
    queryFn: () => ipsecApi.serverInfo().then((res) => res.data),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })

  const { data: detailedStatus, refetch: refetchDetailedStatus, isFetching: isFetchingDetailedStatus } = useQuery({
    queryKey: ['ipsec-statusall'],
    queryFn: () => ipsecApi.statusAll().then((res) => res.data),
    enabled: isStatusModalOpen,
    refetchInterval: isStatusModalOpen ? 5000 : false,
  })

  const { data: logsData, refetch: refetchLogs, isFetching: isFetchingLogs } = useQuery({
    queryKey: ['ipsec-logs', logsConnectionName],
    queryFn: () => ipsecApi.logs(200, logsConnectionName || undefined).then((res) => res.data),
    enabled: isLogsModalOpen,
    refetchInterval: isLogsModalOpen ? 3000 : false,
  })

  // Mutations
  const createMutation = useMutation({
    mutationFn: (data: IPsecConnectionCreate) => ipsecApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-config-preview'] })
      toast({ title: 'Conexão criada com sucesso' })
      setIsAddModalOpen(false)
      setFormData(createInitialForm(serverInfo || undefined))
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao criar conexão',
        description: error.response?.data?.detail || 'Erro desconhecido',
      })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<IPsecConnection> }) =>
      ipsecApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-config-preview'] })
      toast({ title: 'Conexão atualizada' })
      setIsEditModalOpen(false)
      setEditingConnection(null)
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao atualizar conexão',
        description: error.response?.data?.detail || 'Erro desconhecido',
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-config-preview'] })
      toast({ title: 'Conexão excluída' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao excluir conexão' })
    },
  })

  const startMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.start(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
      toast({ title: 'Túnel iniciado' })
    },
    onError: (error: Error & { response?: { data?: { detail?: string | { error?: string; suggestion?: string; error_type?: string } } } }) => {
      const detail = error.response?.data?.detail
      let errorMsg = 'Erro desconhecido'
      let suggestion = ''

      if (typeof detail === 'string') {
        errorMsg = detail
      } else if (detail && typeof detail === 'object') {
        errorMsg = detail.error || 'Erro desconhecido'
        suggestion = detail.suggestion || ''
      }

      toast({
        variant: 'destructive',
        title: 'Falha ao iniciar túnel',
        description: (
          <div className="space-y-1">
            <p>{errorMsg}</p>
            {suggestion && <p className="text-xs opacity-80">{suggestion}</p>}
          </div>
        ),
      })
    },
  })

  const stopMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.stop(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
      toast({ title: 'Túnel parado' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao parar túnel' })
    },
  })

  const restartMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.restart(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
      toast({ title: 'Túnel reiniciado' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao reiniciar túnel' })
    },
  })

  const testFailoverMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.testFailover(id),
    onSuccess: (res: any) => {
      toast({
        title: 'Teste de failover iniciado',
        description: res?.data?.message || 'Bloqueando o caminho ativo; acompanhe o status (auto-restaura).',
      })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Falha no teste de failover', description: error?.response?.data?.detail })
    },
  })

  const switchBackupMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.switchBackup(id),
    onSuccess: (res: any) => {
      toast({ title: 'Switch para backup', description: res?.data?.message })
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Falha ao trocar para backup', description: error?.response?.data?.detail })
    },
  })

  const rollbackMutation = useMutation({
    mutationFn: (id: string) => ipsecApi.rollbackPrimary(id),
    onSuccess: (res: any) => {
      toast({ title: 'Rollback para primário', description: res?.data?.message })
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Falha no rollback', description: error?.response?.data?.detail })
    },
  })

  const [confirmRestartSS, setConfirmRestartSS] = useState(false)
  const restartSSMutation = useMutation({
    mutationFn: () => ipsecApi.restartStrongSwan(),
    onSuccess: () => {
      setConfirmRestartSS(false)
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      toast({ title: 'StrongSwan reiniciado' })
    },
    onError: (error: any) => {
      setConfirmRestartSS(false)
      toast({ variant: 'destructive', title: 'Falha ao reiniciar StrongSwan', description: error?.response?.data?.detail })
    },
  })

  const syncStatusMutation = useMutation({
    mutationFn: () => ipsecApi.syncStatus(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ipsec-connections'] })
      queryClient.invalidateQueries({ queryKey: ['ipsec-status'] })
      toast({ title: 'Status sincronizado' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao sincronizar status' })
    },
  })

  const connections: IPsecConnection[] = connectionsData?.items || []

  // The connection being exported has a backup endpoint? This gates the failover-only
  // fields in the download modal (WAN backup / SLA source / Local ID backup) so a
  // single-link tunnel never shows options that don't apply to it.
  const exportHasBackup = !!(exportConn?.right_ip_backup && exportConn.right_ip_backup.trim())

  const getStatusIcon = (connectionStatus: string) => {
    switch (connectionStatus) {
      case 'active':
        return <CheckCircle2 className="h-4 w-4 text-success" />
      case 'connecting':
        return <Loader2 className="h-4 w-4 text-warning animate-spin" />
      case 'error':
        return <XCircle className="h-4 w-4 text-destructive" />
      default:
        return <AlertCircle className="h-4 w-4 text-muted-foreground" />
    }
  }

  const getStatusColor = (connectionStatus: string) => {
    switch (connectionStatus) {
      case 'active':
        return 'bg-success/20 text-success'
      case 'connecting':
        return 'bg-warning/20 text-warning'
      case 'error':
        return 'bg-destructive/20 text-destructive'
      default:
        return 'bg-muted text-muted-foreground'
    }
  }

  const handleCreateConnection = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim()) {
      toast({ variant: 'destructive', title: 'O nome da conexão é obrigatório' })
      return
    }
    if (!formData.psk.trim()) {
      toast({ variant: 'destructive', title: 'A chave pré-compartilhada é obrigatória' })
      return
    }
    createMutation.mutate(formData as unknown as IPsecConnectionCreate)
  }

  const handleEditConnection = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingConnection) return

    if (!formData.name.trim()) {
      toast({ variant: 'destructive', title: 'O nome da conexão é obrigatório' })
      return
    }

    // Send ONLY changed fields (diff against the loaded connection). This makes the edit
    // a true partial update: a field the user didn't touch is never re-submitted, so it
    // can never accidentally wipe stored values (e.g. right_id / right_ip_backup when you
    // only edit the PSK). The backend's update schema is all-optional, so this is safe.
    const orig = editingConnection
    const updateData: Partial<ConnectionForm> = {}
    const strFields: (keyof ConnectionForm)[] = [
      'name', 'description', 'left_ip', 'left_subnet', 'left_id',
      'right_ip', 'right_ip_backup', 'right_subnet', 'right_id',
      'auth_method', 'ike_version', 'ike_cipher', 'ike_lifetime',
      'esp_cipher', 'key_lifetime', 'dpd_action',
    ]
    for (const f of strFields) {
      const next = ((formData[f] as string) ?? '').trim()
      const prev = (((orig as unknown as Record<string, unknown>)[f] as string) ?? '').trim()
      if (next !== prev) (updateData as Record<string, unknown>)[f] = next
    }
    if (formData.auto_start !== (orig.auto_start ?? true)) updateData.auto_start = formData.auto_start
    if (formData.is_enabled !== (orig.is_enabled ?? true)) updateData.is_enabled = formData.is_enabled
    if (formData.psk && formData.psk !== '********') updateData.psk = formData.psk

    if (Object.keys(updateData).length === 0) {
      toast({ title: 'Nenhuma alteração para salvar' })
      setIsEditModalOpen(false)
      return
    }

    updateMutation.mutate({
      id: editingConnection.id,
      data: updateData as Partial<IPsecConnection>,
    })
  }

  const handleToggleEnabled = (conn: IPsecConnection) => {
    updateMutation.mutate({ id: conn.id, data: { is_enabled: !conn.is_enabled } })
  }

  const openEditModal = (conn: IPsecConnection) => {
    setEditingConnection(conn)
    setFormData({
      name: conn.name,
      description: conn.description || '',
      left_ip: conn.left_ip,
      left_subnet: conn.left_subnet,
      left_id: conn.left_id,
      right_ip: conn.right_ip,
      right_ip_backup: conn.right_ip_backup || '',
      right_subnet: conn.right_subnet,
      right_id: conn.right_id,
      auth_method: conn.auth_method || 'psk',
      psk: '********',
      ike_version: conn.ike_version || 'ikev2',
      ike_cipher: conn.ike_cipher || 'aes256-sha256-modp2048',
      ike_lifetime: conn.ike_lifetime || '8h',
      esp_cipher: conn.esp_cipher || 'aes256-sha256',
      key_lifetime: conn.key_lifetime || '1h',
      auto_start: conn.auto_start ?? true,
      dpd_action: conn.dpd_action || 'restart',
      is_enabled: conn.is_enabled ?? true,
    })
    setShowBackup(!!(conn.right_ip_backup && conn.right_ip_backup.trim()))
    setIsEditModalOpen(true)
  }

  const openAddModal = () => {
    setFormData(createInitialForm(serverInfo || undefined))
    setShowBackup(false)
    setIsAddModalOpen(true)
  }

  const getLiveStatus = (name: string) => {
    return status?.connections?.find((c) => c.name === name)
  }

  const openLogsForConnection = (connectionName: string) => {
    setLogsConnectionName(connectionName)
    setIsLogsModalOpen(true)
  }

  const openAllLogs = () => {
    setLogsConnectionName(null)
    setIsLogsModalOpen(true)
  }

  // Form field change handler
  const updateField = (field: keyof ConnectionForm, value: string | boolean) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="IPsec"
        subtitle="Túneis site-to-site (StrongSwan)"
        actions={
          <Button onClick={openAddModal}>
            <Plus className="h-4 w-4 mr-2" />
            Adicionar Conexão
          </Button>
        }
      />

      {/* Status Card */}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <span className="text-muted-foreground">
          StrongSwan{' '}
          <span className={status?.strongswan_running ? 'text-success font-medium' : 'text-destructive'}>
            {status?.strongswan_running ? 'Em execução' : 'Parado'}
          </span>
        </span>
        <span className="text-muted-foreground">
          Total de Conexões <span className="text-foreground">{status?.total_connections || 0}</span>
        </span>
        <span className="text-muted-foreground">
          Túneis Ativos <span className="text-success">{status?.active_tunnels || 0}</span>
        </span>
        <span className="text-muted-foreground">
          Configurados <span className="text-foreground">{connections.length}</span>
        </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsStatusModalOpen(true)}
          >
            <Terminal className="h-4 w-4 mr-1" />
            Status
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={openAllLogs}
          >
            <FileText className="h-4 w-4 mr-1" />
            Todos os Logs
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => syncStatusMutation.mutate()}
            disabled={syncStatusMutation.isPending}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${syncStatusMutation.isPending ? 'animate-spin' : ''}`} />
            Sincronizar
          </Button>
          <Button variant="ghost" size="sm" onClick={() => refetchStatus()}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <div className="w-px h-5 bg-border mx-0.5" aria-hidden="true" />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setConfirmRestartSS(true)}
            title="Reiniciar o serviço StrongSwan (derruba e renegocia todos os túneis)"
          >
            <RotateCcw className="h-4 w-4 mr-1" />
            Reiniciar
          </Button>
        </div>
      </div>

      {/* Connections Card */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Server className="h-4 w-4" />
            Conexões IPsec
          </CardTitle>
          <CardDescription className="text-xs">
            {connections.length} conex{connections.length !== 1 ? 'ões' : 'ão'} configurada{connections.length !== 1 ? 's' : ''}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : connections.length === 0 ? (
            <div className="text-center py-8">
              <Network className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <p className="text-muted-foreground mb-4">Nenhuma conexão IPsec configurada</p>
              <Button onClick={openAddModal}>
                <Plus className="h-4 w-4 mr-2" />
                Adicionar sua Primeira Conexão
              </Button>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-3 text-left">Nome</th>
                    <th className="px-4 py-3 text-left">Peer Remoto</th>
                    <th className="px-4 py-3 text-left">Sub-redes</th>
                    <th className="px-4 py-3 text-left">IKE</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">Status ao Vivo</th>
                    <th className="px-4 py-3 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {connections.map((conn) => {
                    const liveStatus = getLiveStatus(conn.name)
                    return (
                      <tr key={conn.id} className="border-b hover:bg-muted/50">
                        <td className="px-4 py-3">
                          <div>
                            <p className="font-medium">{conn.name}</p>
                            {conn.description && (
                              <p className="text-xs text-muted-foreground">{conn.description}</p>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          {(() => {
                            // Endpoint que REALMENTE carrega tráfego (lido da política XFRM no
                            // backend). Fallback pro prefer_backup se o status ainda não souber.
                            // Indicador padrão único: chip "ATIVO" (+ "· manual" quando é switch
                            // forçado) no IP em uso — igual pra failover automático e manual.
                            const active = liveStatus?.remote_host
                              || (conn.prefer_backup ? conn.right_ip_backup : conn.right_ip)
                            const hasBackup = !!conn.right_ip_backup
                            const priActive = hasBackup && active === conn.right_ip
                            const bakActive = hasBackup && active === conn.right_ip_backup
                            const chip = (
                              <span className="ml-1.5 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 align-middle">
                                ATIVO{conn.prefer_backup ? ' · manual' : ''}
                              </span>
                            )
                            return (
                              <div>
                                <p className={priActive ? 'font-semibold' : ''}>
                                  {conn.right_ip}{priActive && chip}
                                </p>
                                {hasBackup && (
                                  <p className={bakActive ? 'font-semibold' : 'text-muted-foreground'}>
                                    backup: {conn.right_ip_backup}{bakActive && chip}
                                  </p>
                                )}
                                <p className="text-muted-foreground">ID: {conn.right_id}</p>
                              </div>
                            )
                          })()}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          <div>
                            <p className="text-muted-foreground">Local: {conn.left_subnet}</p>
                            <p className="text-muted-foreground">Remota: {conn.right_subnet}</p>
                          </div>
                        </td>
                        <td className="px-4 py-3 uppercase text-xs">{conn.ike_version}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleToggleEnabled(conn)}
                            disabled={updateMutation.isPending}
                            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium transition-colors ${
                              conn.is_enabled
                                ? 'bg-success/20 text-success hover:bg-success/30'
                                : 'bg-muted text-muted-foreground hover:bg-muted/80'
                            }`}
                          >
                            {conn.is_enabled ? <Shield className="h-3 w-3" /> : <ShieldOff className="h-3 w-3" />}
                            {conn.is_enabled ? 'Habilitada' : 'Desabilitada'}
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          {liveStatus ? (
                            <div>
                              {/* Tunnel Status Badge */}
                              <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${
                                liveStatus.tunnel_status === 'UP'
                                  ? 'bg-success/20 text-success'
                                  : liveStatus.tunnel_status === 'IKE_ONLY'
                                  ? 'bg-warning/20 text-warning'
                                  : liveStatus.tunnel_status === 'CONNECTING'
                                  ? 'bg-primary/20 text-primary'
                                  : 'bg-muted text-muted-foreground'
                              }`}>
                                {liveStatus.tunnel_status === 'UP' ? (
                                  <CheckCircle2 className="h-3 w-3" />
                                ) : liveStatus.tunnel_status === 'IKE_ONLY' ? (
                                  <AlertCircle className="h-3 w-3" />
                                ) : liveStatus.tunnel_status === 'CONNECTING' ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <XCircle className="h-3 w-3" />
                                )}
                                <span>
                                  {liveStatus.tunnel_status === 'UP' ? 'Túnel ATIVO'
                                    : liveStatus.tunnel_status === 'IKE_ONLY' ? 'Apenas IKE'
                                    : liveStatus.tunnel_status === 'CONNECTING' ? 'Conectando'
                                    : 'Inativo'}
                                </span>
                              </div>
                              {/* Uptime */}
                              {liveStatus.uptime && liveStatus.tunnel_status === 'UP' && (
                                <p className="text-xs text-muted-foreground mt-1">Ativo há: {liveStatus.uptime}</p>
                              )}
                              {/* Traffic stats */}
                              {liveStatus.tunnel_status === 'UP' && (liveStatus.bytes_in !== undefined || liveStatus.bytes_out !== undefined) && (
                                <p className="text-xs text-muted-foreground mt-0.5">
                                  {liveStatus.bytes_in || 0} B entrada / {liveStatus.bytes_out || 0} B saída
                                </p>
                              )}
                              {/* Error hint for IKE_ONLY */}
                              {liveStatus.tunnel_status === 'IKE_ONLY' && liveStatus.error_hint && (
                                <p className="text-xs text-warning mt-1 max-w-[200px]" title={liveStatus.error_hint}>
                                  {liveStatus.error_hint}
                                </p>
                              )}
                            </div>
                          ) : (
                            <div>
                              <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${getStatusColor(conn.status)}`}>
                                {getStatusIcon(conn.status)}
                                <span className="capitalize">{conn.status}</span>
                              </div>
                              {conn.last_error && conn.status === 'error' && (
                                <p className="text-xs text-destructive mt-1 max-w-[200px] truncate" title={conn.last_error}>
                                  {conn.last_error}
                                </p>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1">
                            {conn.status === 'active' ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => stopMutation.mutate(conn.id)}
                                disabled={stopMutation.isPending}
                                title="Parar túnel"
                              >
                                <Square className="h-4 w-4" />
                              </Button>
                            ) : (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => startMutation.mutate(conn.id)}
                                disabled={startMutation.isPending || !conn.is_enabled}
                                title="Iniciar túnel"
                              >
                                <Play className="h-4 w-4" />
                              </Button>
                            )}
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm" title="Mais ações">
                                  <MoreVertical className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent>
                                <DropdownMenuItem onSelect={() => openEditModal(conn)}>
                                  <Pencil className="h-4 w-4" /> Editar
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => setPreviewConn(conn)}>
                                  <Eye className="h-4 w-4" /> Ver config gerada
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => openLogsForConnection(conn.name)}>
                                  <FileText className="h-4 w-4" /> Ver logs
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => {
                                  setExportForm((f) => ({
                                    ...f,
                                    base: (conn.name || '').replace(/[^A-Za-z0-9-]/g, '').replace(/^-+|-+$/g, '').slice(0, 12),
                                    client_lan: conn.right_subnet || '',
                                  }))
                                  setExportConn(conn)
                                }}>
                                  <Download className="h-4 w-4" /> Baixar config
                                </DropdownMenuItem>
                                {conn.status === 'active' && (
                                  <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      disabled={restartMutation.isPending}
                                      onSelect={() => restartMutation.mutate(conn.id)}
                                    >
                                      <RotateCcw className="h-4 w-4" /> Reiniciar túnel
                                    </DropdownMenuItem>
                                  </>
                                )}
                                {conn.right_ip_backup && (
                                  <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuLabel>Failover</DropdownMenuLabel>
                                    <DropdownMenuItem
                                      disabled={testFailoverMutation.isPending}
                                      onSelect={() => testFailoverMutation.mutate(conn.id)}
                                    >
                                      <Zap className="h-4 w-4" /> Testar failover
                                    </DropdownMenuItem>
                                    {conn.prefer_backup ? (
                                      <DropdownMenuItem
                                        disabled={rollbackMutation.isPending}
                                        onSelect={() => rollbackMutation.mutate(conn.id)}
                                      >
                                        <Undo2 className="h-4 w-4" /> Rollback para o primário
                                      </DropdownMenuItem>
                                    ) : (
                                      <DropdownMenuItem
                                        disabled={switchBackupMutation.isPending}
                                        onSelect={() => switchBackupMutation.mutate(conn.id)}
                                      >
                                        <ArrowLeftRight className="h-4 w-4" /> Switch para backup
                                      </DropdownMenuItem>
                                    )}
                                  </>
                                )}
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  destructive
                                  onSelect={() => { setDeleteConn(conn); setDeleteText('') }}
                                >
                                  <Trash2 className="h-4 w-4" /> Excluir
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Connection Modal */}
      <Dialog open={isAddModalOpen} onOpenChange={setIsAddModalOpen}>
        <DialogContent onClose={() => setIsAddModalOpen(false)} className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Adicionar Conexão IPsec</DialogTitle>
            <DialogDescription>Configure um novo túnel VPN IPsec site-to-site</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateConnection}>
            <div className="space-y-6 mt-4">
              {/* Connection Details */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Detalhes da Conexão</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="add-name">Nome da Conexão *</Label>
                    <Input
                      id="add-name"
                      value={formData.name}
                      onChange={(e) => updateField('name', e.target.value)}
                      placeholder="IPSECtoOffice"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-description">Descrição</Label>
                    <Input
                      id="add-description"
                      value={formData.description}
                      onChange={(e) => updateField('description', e.target.value)}
                      placeholder="VPN para o escritório principal"
                    />
                  </div>
                </div>
              </div>

              {/* Local Gateway */}
              <div className="space-y-4 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center justify-between">
                  <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Gateway Local (Este Servidor)</h3>
                  {serverInfo?.private_ip && (
                    <span className="text-xs text-success bg-success/10 px-2 py-1 rounded">Detectado automaticamente</span>
                  )}
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="add-left_ip">IP Privado</Label>
                    <Input
                      id="add-left_ip"
                      value={formData.left_ip}
                      onChange={(e) => updateField('left_ip', e.target.value)}
                      placeholder="10.30.1.254"
                      className="bg-background"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-left_subnet">Sub-rede Local</Label>
                    <Input
                      id="add-left_subnet"
                      value={formData.left_subnet}
                      onChange={(e) => updateField('left_subnet', e.target.value)}
                      placeholder="10.30.0.0/16"
                      className="bg-background"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-left_id">IP Público / ID</Label>
                    <Input
                      id="add-left_id"
                      value={formData.left_id}
                      onChange={(e) => updateField('left_id', e.target.value)}
                      placeholder="54.94.19.176"
                      className="bg-background"
                    />
                  </div>
                </div>
              </div>

              {/* Remote Gateway */}
              <div className="space-y-4 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Gateway Remoto (Peer)</h3>
                  <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground">
                    <input
                      type="checkbox"
                      checked={showBackup}
                      onChange={(e) => {
                        const on = e.target.checked
                        setShowBackup(on)
                        if (!on) updateField('right_ip_backup', '')
                      }}
                      className="rounded"
                    />
                    <span>Habilitar link de backup — failover (homologado em FortiGate)</span>
                  </label>
                </div>
                {showBackup && (
                  <p className="text-xs text-amber-600 dark:text-amber-500">
                    ⚠ Failover com 2 links (primário + backup) é homologado apenas em <strong>FortiGate</strong>. Em pfSense, Endian ou outros equipamentos, use só o link primário.
                  </p>
                )}
                {/* Linha 1 — só os IPs (primário e, se habilitado, o backup) */}
                <div className={`grid gap-4 ${showBackup ? 'md:grid-cols-2' : 'md:grid-cols-1'}`}>
                  <div className="space-y-2">
                    <Label htmlFor="add-right_ip">IP Público (primário) *</Label>
                    <Input
                      id="add-right_ip"
                      value={formData.right_ip}
                      onChange={(e) => updateField('right_ip', e.target.value)}
                      placeholder="187.92.78.242"
                    />
                    <p className="text-xs text-muted-foreground">IP público do peer remoto</p>
                  </div>
                  {showBackup && (
                    <div className="space-y-2">
                      <Label htmlFor="add-right_ip_backup">IP de Backup (failover)</Label>
                      <Input
                        id="add-right_ip_backup"
                        value={formData.right_ip_backup}
                        onChange={(e) => updateField('right_ip_backup', e.target.value)}
                        placeholder="2º IP do peer"
                      />
                      <p className="text-xs text-muted-foreground">2º IP fixo do peer p/ failover (HA)</p>
                    </div>
                  )}
                </div>
                {/* Linha 2 — Peer ID (um nome/FQDN; não precisa ser IP) */}
                <div className="space-y-2">
                  <Label htmlFor="add-right_id">ID do Peer</Label>
                  <Input
                    id="add-right_id"
                    value={formData.right_id}
                    onChange={(e) => updateField('right_id', e.target.value)}
                    placeholder="ex: matriz-fw ou vpn.cliente.com"
                  />
                  <p className="text-xs text-muted-foreground">Pode ser um nome/FQDN (ex: matriz-fw, vpn.cliente.com) ou o IP. O mesmo ID vale para o link primário e o backup.</p>
                </div>
                {/* Linha 3 — sub-rede(s) remota(s) */}
                <div className="space-y-2">
                  <Label htmlFor="add-right_subnet">Sub-rede(s) Remota(s) *</Label>
                  <Input
                    id="add-right_subnet"
                    value={formData.right_subnet}
                    onChange={(e) => updateField('right_subnet', e.target.value)}
                    placeholder="10.0.0.0/24, 192.168.1.0/24"
                  />
                  <p className="text-xs text-muted-foreground">Use vírgula para separar múltiplas sub-redes</p>
                </div>
              </div>

              {/* Authentication */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Autenticação</h3>
                <div className="space-y-2">
                  <Label htmlFor="add-psk">Chave Pré-Compartilhada (PSK) *</Label>
                  <Input
                    id="add-psk"
                    type="password"
                    value={formData.psk}
                    onChange={(e) => updateField('psk', e.target.value)}
                    placeholder="Digite um segredo compartilhado forte"
                  />
                  <p className="text-xs text-muted-foreground">Mínimo de 8 caracteres. Deve corresponder em ambos os lados.</p>
                </div>
              </div>

              {/* Encryption Settings */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Configurações de Criptografia</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="add-ike_version">Versão IKE</Label>
                    <Select
                      id="add-ike_version"
                      value={formData.ike_version}
                      onChange={(e) => updateField('ike_version', e.target.value)}
                      options={IKE_VERSION_OPTIONS}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-dpd_action">Ação DPD</Label>
                    <Select
                      id="add-dpd_action"
                      value={formData.dpd_action}
                      onChange={(e) => updateField('dpd_action', e.target.value)}
                      options={DPD_ACTION_OPTIONS}
                    />
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="add-ike_cipher">Cifra IKE (Fase 1)</Label>
                    <Select
                      id="add-ike_cipher"
                      value={formData.ike_cipher}
                      onChange={(e) => updateField('ike_cipher', e.target.value)}
                      options={IKE_CIPHER_PRESETS}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-esp_cipher">Cifra ESP (Fase 2)</Label>
                    <Select
                      id="add-esp_cipher"
                      value={formData.esp_cipher}
                      onChange={(e) => updateField('esp_cipher', e.target.value)}
                      options={ESP_CIPHER_PRESETS}
                    />
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="add-ike_lifetime">Tempo de Vida IKE</Label>
                    <Input
                      id="add-ike_lifetime"
                      value={formData.ike_lifetime}
                      onChange={(e) => updateField('ike_lifetime', e.target.value)}
                      placeholder="8h"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="add-key_lifetime">Tempo de Vida da Chave</Label>
                    <Input
                      id="add-key_lifetime"
                      value={formData.key_lifetime}
                      onChange={(e) => updateField('key_lifetime', e.target.value)}
                      placeholder="1h"
                    />
                  </div>
                </div>
              </div>

              {/* Options */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Opções</h3>
                <div className="flex items-center gap-6">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.auto_start}
                      onChange={(e) => updateField('auto_start', e.target.checked)}
                      className="rounded"
                    />
                    <span className="text-sm">Iniciar automaticamente no boot</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.is_enabled}
                      onChange={(e) => updateField('is_enabled', e.target.checked)}
                      className="rounded"
                    />
                    <span className="text-sm">Habilitado</span>
                  </label>
                </div>
              </div>
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsAddModalOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Criando...' : 'Criar Conexão'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit Connection Modal */}
      <Dialog open={isEditModalOpen} onOpenChange={setIsEditModalOpen}>
        <DialogContent onClose={() => setIsEditModalOpen(false)} className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Editar Conexão IPsec</DialogTitle>
            <DialogDescription>Modifique a configuração da conexão IPsec</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEditConnection}>
            <div className="space-y-6 mt-4">
              {/* Connection Details */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Detalhes da Conexão</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="edit-name">Nome da Conexão *</Label>
                    <Input
                      id="edit-name"
                      value={formData.name}
                      onChange={(e) => updateField('name', e.target.value)}
                      placeholder="IPSECtoOffice"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-description">Descrição</Label>
                    <Input
                      id="edit-description"
                      value={formData.description}
                      onChange={(e) => updateField('description', e.target.value)}
                      placeholder="VPN para o escritório principal"
                    />
                  </div>
                </div>
              </div>

              {/* Local Gateway */}
              <div className="space-y-4 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center justify-between">
                  <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Gateway Local (Este Servidor)</h3>
                  {serverInfo?.private_ip && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (serverInfo) {
                          updateField('left_ip', serverInfo.private_ip || '')
                          updateField('left_subnet', serverInfo.local_subnet || '')
                          updateField('left_id', serverInfo.public_ip || '')
                        }
                      }}
                    >
                      <RefreshCw className="h-3 w-3 mr-1" />
                      Detectar automaticamente
                    </Button>
                  )}
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="edit-left_ip">IP Privado</Label>
                    <Input
                      id="edit-left_ip"
                      value={formData.left_ip}
                      onChange={(e) => updateField('left_ip', e.target.value)}
                      placeholder="10.30.1.254"
                      className="bg-background"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-left_subnet">Sub-rede Local</Label>
                    <Input
                      id="edit-left_subnet"
                      value={formData.left_subnet}
                      onChange={(e) => updateField('left_subnet', e.target.value)}
                      placeholder="10.30.0.0/16"
                      className="bg-background"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-left_id">IP Público / ID</Label>
                    <Input
                      id="edit-left_id"
                      value={formData.left_id}
                      onChange={(e) => updateField('left_id', e.target.value)}
                      placeholder="54.94.19.176"
                      className="bg-background"
                    />
                  </div>
                </div>
              </div>

              {/* Remote Gateway */}
              <div className="space-y-4 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Gateway Remoto (Peer)</h3>
                  <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground">
                    <input
                      type="checkbox"
                      checked={showBackup}
                      onChange={(e) => {
                        const on = e.target.checked
                        setShowBackup(on)
                        if (!on) updateField('right_ip_backup', '')
                      }}
                      className="rounded"
                    />
                    <span>Habilitar link de backup — failover (homologado em FortiGate)</span>
                  </label>
                </div>
                {showBackup && (
                  <p className="text-xs text-amber-600 dark:text-amber-500">
                    ⚠ Failover com 2 links (primário + backup) é homologado apenas em <strong>FortiGate</strong>. Em pfSense, Endian ou outros equipamentos, use só o link primário.
                  </p>
                )}
                {/* Linha 1 — só os IPs (primário e, se habilitado, o backup) */}
                <div className={`grid gap-4 ${showBackup ? 'md:grid-cols-2' : 'md:grid-cols-1'}`}>
                  <div className="space-y-2">
                    <Label htmlFor="edit-right_ip">IP Público (primário) *</Label>
                    <Input
                      id="edit-right_ip"
                      value={formData.right_ip}
                      onChange={(e) => updateField('right_ip', e.target.value)}
                      placeholder="187.92.78.242"
                    />
                    <p className="text-xs text-muted-foreground">IP público do peer remoto</p>
                  </div>
                  {showBackup && (
                    <div className="space-y-2">
                      <Label htmlFor="edit-right_ip_backup">IP de Backup (failover)</Label>
                      <Input
                        id="edit-right_ip_backup"
                        value={formData.right_ip_backup}
                        onChange={(e) => updateField('right_ip_backup', e.target.value)}
                        placeholder="2º IP do peer"
                      />
                      <p className="text-xs text-muted-foreground">2º IP fixo do peer p/ failover (HA)</p>
                    </div>
                  )}
                </div>
                {/* Linha 2 — Peer ID (um nome/FQDN; não precisa ser IP) */}
                <div className="space-y-2">
                  <Label htmlFor="edit-right_id">ID do Peer</Label>
                  <Input
                    id="edit-right_id"
                    value={formData.right_id}
                    onChange={(e) => updateField('right_id', e.target.value)}
                    placeholder="ex: matriz-fw ou vpn.cliente.com"
                  />
                  <p className="text-xs text-muted-foreground">Pode ser um nome/FQDN (ex: matriz-fw, vpn.cliente.com) ou o IP. O mesmo ID vale para o link primário e o backup.</p>
                </div>
                {/* Linha 3 — sub-rede(s) remota(s) */}
                <div className="space-y-2">
                  <Label htmlFor="edit-right_subnet">Sub-rede(s) Remota(s) *</Label>
                  <Input
                    id="edit-right_subnet"
                    value={formData.right_subnet}
                    onChange={(e) => updateField('right_subnet', e.target.value)}
                    placeholder="10.0.0.0/24, 192.168.1.0/24"
                  />
                  <p className="text-xs text-muted-foreground">Use vírgula para separar múltiplas sub-redes</p>
                </div>
              </div>

              {/* Authentication */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Autenticação</h3>
                <div className="space-y-2">
                  <Label htmlFor="edit-psk">Chave Pré-Compartilhada (PSK)</Label>
                  <Input
                    id="edit-psk"
                    type="password"
                    value={formData.psk}
                    onChange={(e) => updateField('psk', e.target.value)}
                    placeholder="Deixe inalterado ou digite uma nova chave"
                  />
                  <p className="text-xs text-muted-foreground">Deixe como ******** para manter a chave atual, ou digite uma nova</p>
                </div>
              </div>

              {/* Encryption Settings */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Configurações de Criptografia</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="edit-ike_version">Versão IKE</Label>
                    <Select
                      id="edit-ike_version"
                      value={formData.ike_version}
                      onChange={(e) => updateField('ike_version', e.target.value)}
                      options={IKE_VERSION_OPTIONS}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-dpd_action">Ação DPD</Label>
                    <Select
                      id="edit-dpd_action"
                      value={formData.dpd_action}
                      onChange={(e) => updateField('dpd_action', e.target.value)}
                      options={DPD_ACTION_OPTIONS}
                    />
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="edit-ike_cipher">Cifra IKE (Fase 1)</Label>
                    <Select
                      id="edit-ike_cipher"
                      value={formData.ike_cipher}
                      onChange={(e) => updateField('ike_cipher', e.target.value)}
                      options={IKE_CIPHER_PRESETS}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-esp_cipher">Cifra ESP (Fase 2)</Label>
                    <Select
                      id="edit-esp_cipher"
                      value={formData.esp_cipher}
                      onChange={(e) => updateField('esp_cipher', e.target.value)}
                      options={ESP_CIPHER_PRESETS}
                    />
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="edit-ike_lifetime">Tempo de Vida IKE</Label>
                    <Input
                      id="edit-ike_lifetime"
                      value={formData.ike_lifetime}
                      onChange={(e) => updateField('ike_lifetime', e.target.value)}
                      placeholder="8h"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-key_lifetime">Tempo de Vida da Chave</Label>
                    <Input
                      id="edit-key_lifetime"
                      value={formData.key_lifetime}
                      onChange={(e) => updateField('key_lifetime', e.target.value)}
                      placeholder="1h"
                    />
                  </div>
                </div>
              </div>

              {/* Options */}
              <div className="space-y-4">
                <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Opções</h3>
                <div className="flex items-center gap-6">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.auto_start}
                      onChange={(e) => updateField('auto_start', e.target.checked)}
                      className="rounded"
                    />
                    <span className="text-sm">Iniciar automaticamente no boot</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.is_enabled}
                      onChange={(e) => updateField('is_enabled', e.target.checked)}
                      className="rounded"
                    />
                    <span className="text-sm">Habilitado</span>
                  </label>
                </div>
              </div>
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsEditModalOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? 'Salvando...' : 'Salvar Alterações'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Per-connection generated config */}
      <Dialog open={!!previewConn} onOpenChange={(o) => { if (!o) setPreviewConn(null) }}>
        <DialogContent onClose={() => setPreviewConn(null)} className="max-w-3xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle>Config gerada — {previewConn?.name}</DialogTitle>
            <DialogDescription>O que o EdgeGate escreve no swanctl para esta conexão (PSK oculto)</DialogDescription>
          </DialogHeader>
          <div className="mt-4">
            <pre className="p-4 bg-muted rounded-lg text-xs overflow-auto max-h-[55vh] font-mono whitespace-pre">
              {connConfigLoading ? 'Carregando...' : (connConfig || 'Sem config gerada.')}
            </pre>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreviewConn(null)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation (type-to-confirm) */}
      <Dialog open={!!deleteConn} onOpenChange={(o) => { if (!o) { setDeleteConn(null); setDeleteText('') } }}>
        <DialogContent onClose={() => { setDeleteConn(null); setDeleteText('') }} className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <Trash2 className="h-5 w-5" /> Excluir conexão
            </DialogTitle>
            <DialogDescription>
              Remove o túnel <span className="font-semibold text-foreground">{deleteConn?.name}</span> e derruba a conexão IPsec. Esta ação não pode ser desfeita.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-2 space-y-2">
            <Label htmlFor="del-confirm">
              Para confirmar, digite o nome do túnel: <span className="font-mono text-foreground">{deleteConn?.name}</span>
            </Label>
            <Input
              id="del-confirm"
              value={deleteText}
              onChange={(e) => setDeleteText(e.target.value)}
              placeholder={deleteConn?.name}
              autoComplete="off"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setDeleteConn(null); setDeleteText('') }}>Cancelar</Button>
            <Button
              variant="destructive"
              disabled={deleteText !== deleteConn?.name || deleteMutation.isPending}
              onClick={() => {
                if (!deleteConn) return
                deleteMutation.mutate(deleteConn.id)
                setDeleteConn(null); setDeleteText('')
              }}
            >
              {deleteMutation.isPending ? 'Excluindo…' : 'Excluir'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Export config for the peer device */}
      <Dialog open={!!exportConn} onOpenChange={(o) => { if (!o) setExportConn(null) }}>
        <DialogContent onClose={() => setExportConn(null)} className="max-w-4xl max-h-[88vh]">
          <DialogHeader>
            <DialogTitle>Baixar config — {exportConn?.name}</DialogTitle>
            <DialogDescription>
              {exportForm.target === 'generic'
                ? 'Genérico = parâmetros para configurar em qualquer equipamento.'
                : exportHasBackup
                  ? 'FortiGate = script de CLI com SD-WAN + failover (2 links), com o PSK real.'
                  : 'FortiGate = túnel único em zona SD-WAN (pronto p/ failover), com o PSK real.'}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 md:grid-cols-[280px_1fr] gap-4 mt-3">
            <div className="space-y-3 overflow-auto max-h-[60vh] pr-1">
              <div>
                <Label>Formato</Label>
                <Select
                  value={exportForm.target}
                  onChange={(e) => setExportForm((f) => ({ ...f, target: e.target.value }))}
                  options={[{ value: 'fortigate', label: 'FortiGate (CLI)' }, { value: 'generic', label: 'Genérico (parâmetros)' }]}
                />
              </div>
              {exportForm.target === 'fortigate' && (
                <>
                  <div>
                    <Label>Versão FortiOS</Label>
                    <Select
                      value={exportForm.fortios}
                      onChange={(e) => setExportForm((f) => ({ ...f, fortios: e.target.value }))}
                      options={[{ value: '7.4', label: '7.4' }, { value: '7.2', label: '7.2' }, { value: '7.0', label: '7.0' }]}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div><Label>WAN primário</Label><Input value={exportForm.wan_pri} onChange={(e) => setExportForm((f) => ({ ...f, wan_pri: e.target.value }))} onBlur={(e) => setExportForm((f) => ({ ...f, wan_pri: e.target.value.trim() }))} placeholder="ex: wan1" /></div>
                    {exportHasBackup && (
                      <div><Label>WAN backup</Label><Input value={exportForm.wan_bak} onChange={(e) => setExportForm((f) => ({ ...f, wan_bak: e.target.value }))} onBlur={(e) => setExportForm((f) => ({ ...f, wan_bak: e.target.value.trim() }))} placeholder="ex: wan2" /></div>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div><Label>Interface LAN</Label><Input value={exportForm.lan_if} onChange={(e) => setExportForm((f) => ({ ...f, lan_if: e.target.value }))} onBlur={(e) => setExportForm((f) => ({ ...f, lan_if: e.target.value.trim() }))} placeholder="ex: internal" /></div>
                    <div><Label>Source do SLA</Label><Input value={exportForm.sla_src} onChange={(e) => setExportForm((f) => ({ ...f, sla_src: e.target.value }))} onBlur={(e) => setExportForm((f) => ({ ...f, sla_src: e.target.value.trim() }))} placeholder="ex: IP LAN do FortiGate" /></div>
                  </div>
                  <div>
                    <Label>Nome base (FortiGate)</Label>
                    <Input
                      value={exportForm.base}
                      maxLength={12}
                      onChange={(e) => setExportForm((f) => ({ ...f, base: e.target.value.replace(/[^A-Za-z0-9-]/g, '') }))}
                      placeholder="ex: VPN-AWS"
                    />
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      túnel {(exportForm.base || '...')}-01{exportHasBackup ? '/-02' : ''} · SLA {exportForm.base.replace(/[^A-Za-z0-9]/g, '') || '...'} · {exportForm.base.length}/12
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {exportHasBackup
                      ? 'O source do SLA precisa ser um IP do Forti dentro da rede do cliente. Nome do túnel ≤ 15 chars; SLA sem hífen (auto).'
                      : 'Túnel único em zona SD-WAN (pronto p/ failover). Informe o Source do SLA (IP do Forti na rede do cliente). Nome do túnel ≤ 15 chars.'}
                  </p>
                </>
              )}
              {exportForm.target === 'generic' && (
                <p className="text-xs text-muted-foreground">Só os parâmetros da IPsec — para configurar em pfSense, Endian, MikroTik, etc.</p>
              )}
            </div>
            <div className="min-w-0">
              <pre className="p-4 bg-muted rounded-lg text-xs overflow-auto max-h-[60vh] font-mono whitespace-pre">
                {exportLoading ? 'Gerando…' : (exportText || '')}
              </pre>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setExportConn(null)}>Fechar</Button>
            <Button variant="outline" onClick={() => { if (exportText) copyText(exportText) }}>
              <Copy className="h-4 w-4 mr-2" /> Copiar
            </Button>
            <Button onClick={downloadExport} disabled={!exportText}>
              <Download className="h-4 w-4 mr-2" /> Baixar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* IPsec Status Modal */}
      <Dialog open={isStatusModalOpen} onOpenChange={setIsStatusModalOpen}>
        <DialogContent onClose={() => setIsStatusModalOpen(false)} className="max-w-4xl max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Terminal className="h-5 w-5" />
              Status do IPsec
            </DialogTitle>
            <DialogDescription>
              Saída detalhada do status do StrongSwan (ipsec statusall)
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                {isFetchingDetailedStatus && (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Atualizando...</span>
                  </>
                )}
                {!isFetchingDetailedStatus && (
                  <span>Atualização automática a cada 5s</span>
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={() => refetchDetailedStatus()}>
                <RefreshCw className={`h-4 w-4 ${isFetchingDetailedStatus ? 'animate-spin' : ''}`} />
              </Button>
            </div>
            <pre className="p-4 bg-black text-success rounded-lg text-xs overflow-auto max-h-[60vh] font-mono whitespace-pre-wrap">
              {detailedStatus?.success === false
                ? `Erro: ${detailedStatus?.output || 'Erro desconhecido'}`
                : detailedStatus?.output || detailedStatus?.stdout || 'Carregando...'}
            </pre>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsStatusModalOpen(false)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* IPsec Logs Modal */}
      <Dialog open={isLogsModalOpen} onOpenChange={(open) => { setIsLogsModalOpen(open); if (!open) setLogsConnectionName(null); }}>
        <DialogContent onClose={() => { setIsLogsModalOpen(false); setLogsConnectionName(null); }} className="max-w-4xl max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              {logsConnectionName ? `Logs: ${logsConnectionName}` : 'Todos os Logs do StrongSwan'}
            </DialogTitle>
            <DialogDescription>
              {logsConnectionName
                ? `Entradas de log da conexão "${logsConnectionName}"`
                : 'Todas as entradas recentes de log do IPsec/StrongSwan'}
              {logsData?.source && <span className="ml-1">({logsData.source})</span>}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                {isFetchingLogs && (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Atualizando...</span>
                  </>
                )}
                {!isFetchingLogs && (
                  <span>Atualização automática a cada 3s (Ao Vivo)</span>
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={() => refetchLogs()}>
                <RefreshCw className={`h-4 w-4 ${isFetchingLogs ? 'animate-spin' : ''}`} />
              </Button>
            </div>
            <pre className="p-4 bg-black text-gray-300 rounded-lg text-xs overflow-auto max-h-[60vh] font-mono whitespace-pre-wrap">
              {logsData?.success === false
                ? `Erro: ${logsData?.logs || 'Não foi possível obter os logs'}`
                : logsData?.logs || 'Carregando logs...'}
            </pre>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsLogsModalOpen(false)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Restart StrongSwan confirmation */}
      <Dialog open={confirmRestartSS} onOpenChange={setConfirmRestartSS}>
        <DialogContent onClose={() => setConfirmRestartSS(false)}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><RotateCcw className="h-5 w-5 text-primary" /> Reiniciar StrongSwan</DialogTitle>
            <DialogDescription>
              Reinicia o serviço IPsec (StrongSwan). Todos os túneis site-to-site caem e renegociam — pode haver alguns segundos de indisponibilidade.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmRestartSS(false)}>Cancelar</Button>
            <Button onClick={() => restartSSMutation.mutate()} disabled={restartSSMutation.isPending} className="gap-2">
              <RotateCcw className="h-4 w-4" />
              {restartSSMutation.isPending ? 'Reiniciando…' : 'Reiniciar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
