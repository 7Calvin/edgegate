import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { proxyApi, acmeApi } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import { PageHeader } from '@/components/PageHeader'
import { formatDateTime } from '@/lib/tz'
import {
  Globe,
  Plus,
  Trash2,
  Pencil,
  Eye,
  Settings,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Heart,
  Shield,
  ShieldOff,
  Lock,
  RotateCcw,
  Copy,
  Loader2,
  FileKey,
} from 'lucide-react'
import type { ProxyRoute, ProxyRouteCreate, CertificateListResponse, ACMEChallenge } from '@/types'

interface RouteForm {
  name: string
  hostname: string
  backend_url: string
  path_prefix: string
  strip_prefix: boolean
  ssl_mode: string
  force_https: boolean
  health_check_type: string
  health_check_path: string
  health_check_interval: string
  pass_host_header: boolean
  custom_request_headers: string
  custom_response_headers: string
  rate_limit_average: string
  rate_limit_burst: string
  is_enabled: boolean
}

const SSL_MODE_OPTIONS = [
  { value: 'letsencrypt', label: "Let's Encrypt (HTTP-01)" },
  { value: 'letsencrypt_dns', label: "Let's Encrypt (DNS-01)" },
  { value: 'custom', label: 'Certificado personalizado' },
  { value: 'none', label: 'Sem SSL (apenas HTTP)' },
]

const HEALTH_CHECK_OPTIONS = [
  { value: 'http', label: 'HTTP' },
  { value: 'tcp', label: 'TCP' },
  { value: 'none', label: 'Desativado' },
]

const createInitialForm = (): RouteForm => ({
  name: '',
  hostname: '',
  backend_url: '',
  path_prefix: '',
  strip_prefix: false,
  ssl_mode: 'letsencrypt',
  force_https: true,
  health_check_type: 'http',
  health_check_path: '/',
  health_check_interval: '30s',
  pass_host_header: true,
  custom_request_headers: '',
  custom_response_headers: '',
  rate_limit_average: '',
  rate_limit_burst: '',
  is_enabled: true,
})

export default function ReverseProxyPage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isConfigPreviewOpen, setIsConfigPreviewOpen] = useState(false)
  const [formData, setFormData] = useState<RouteForm>(createInitialForm())
  const [editingRoute, setEditingRoute] = useState<ProxyRoute | null>(null)
  const [isDnsDialogOpen, setIsDnsDialogOpen] = useState(false)
  const [dnsChallenge, setDnsChallenge] = useState<ACMEChallenge | null>(null)
  const [dnsRouteContext, setDnsRouteContext] = useState<ProxyRoute | null>(null)
  const [isVerifying, setIsVerifying] = useState(false)
  const [verifyResult, setVerifyResult] = useState<{ success: boolean; message: string } | null>(null)

  // Queries
  const { data: routesData, isLoading } = useQuery({
    queryKey: ['proxy-routes'],
    queryFn: () => proxyApi.list().then((res) => res.data),
  })

  const { data: traefikStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['traefik-status'],
    queryFn: () => proxyApi.status().then((res) => res.data),
    refetchInterval: 15000,
  })

  const { data: certsData, refetch: refetchCerts } = useQuery<CertificateListResponse>({
    queryKey: ['proxy-certificates'],
    queryFn: () => proxyApi.certificates().then((res) => res.data),
    refetchInterval: 60000,
  })

  const { data: configPreview } = useQuery({
    queryKey: ['proxy-config-preview'],
    queryFn: () => proxyApi.previewConfig().then((res) => res.data),
    enabled: isConfigPreviewOpen,
  })

  // Mutations
  const getErrorMessage = (error: Error & { response?: { data?: { detail?: unknown; message?: string; details?: Array<{ msg?: string }> } }; status?: number }) => {
    const data = error.response?.data
    if (data?.detail) {
      if (typeof data.detail === 'string') return data.detail
      if (Array.isArray(data.detail)) {
        return data.detail.map((d: { msg?: string; message?: string }) => d.msg || d.message || JSON.stringify(d)).join('; ')
      }
      return JSON.stringify(data.detail)
    }
    if (data?.details?.length) return data.details.map((d) => d.msg).join('; ')
    if (data?.message) return data.message
    return error.message || 'Unknown error'
  }

  const createMutation = useMutation({
    mutationFn: (data: ProxyRouteCreate) => proxyApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
      queryClient.invalidateQueries({ queryKey: ['proxy-config-preview'] })
      toast({ title: 'Rota criada — aplicando configuração...' })
      setIsAddModalOpen(false)
      setFormData(createInitialForm())
      // Auto-apply config after create
      applyMutation.mutate()
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao criar rota',
        description: getErrorMessage(error),
      })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<ProxyRoute> }) =>
      proxyApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
      queryClient.invalidateQueries({ queryKey: ['proxy-config-preview'] })
      toast({ title: 'Rota atualizada — aplicando configuração...' })
      setIsEditModalOpen(false)
      setEditingRoute(null)
      // Auto-apply config after update
      applyMutation.mutate()
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao atualizar rota',
        description: getErrorMessage(error),
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => proxyApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
      queryClient.invalidateQueries({ queryKey: ['proxy-config-preview'] })
      toast({ title: 'Rota excluída — aplicando configuração...' })
      // Auto-apply config after delete
      applyMutation.mutate()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao excluir rota' })
    },
  })

  const applyMutation = useMutation({
    mutationFn: () => proxyApi.apply(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
      queryClient.invalidateQueries({ queryKey: ['traefik-status'] })
      toast({ title: 'Configuração aplicada com sucesso' })
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao aplicar configuração',
        description: getErrorMessage(error),
      })
    },
  })

  const healthCheckMutation = useMutation({
    mutationFn: () => proxyApi.healthCheckAll(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
      toast({ title: 'Verificação de saúde concluída' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha na verificação de saúde' })
    },
  })

  const singleHealthCheckMutation = useMutation({
    mutationFn: (id: string) => proxyApi.healthCheck(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
      toast({ title: 'Verificação de saúde concluída' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha na verificação de saúde' })
    },
  })

  const renewCertMutation = useMutation({
    mutationFn: (domain: string) => proxyApi.renewCertificate(domain),
    onSuccess: (res) => {
      toast({
        title: 'Renovação de certificado iniciada',
        description: res.data?.message || 'O Traefik está reemitindo o certificado. Pode levar até 30s para aparecer.',
      })
      // Delay refetch to give Traefik time to re-issue
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['proxy-certificates'] })
      }, 15000)
      // Also refetch sooner in case it's fast
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['proxy-certificates'] })
      }, 5000)
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao renovar certificado',
        description: getErrorMessage(error),
      })
    },
  })

  const deleteCertMutation = useMutation({
    mutationFn: (domain: string) => proxyApi.deleteCertificate(domain),
    onSuccess: (_, domain) => {
      queryClient.invalidateQueries({ queryKey: ['proxy-certificates'] })
      toast({ title: `Certificado de ${domain} excluído` })
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao excluir certificado',
        description: getErrorMessage(error),
      })
    },
  })

  const requestDnsMutation = useMutation({
    mutationFn: (data: { domain: string; proxy_route_id?: string }) =>
      acmeApi.requestDnsChallenge(data),
    onSuccess: (res) => {
      setDnsChallenge(res.data)
      setVerifyResult(null)
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao solicitar desafio DNS',
        description: getErrorMessage(error),
      })
    },
  })

  const verifyDnsMutation = useMutation({
    mutationFn: (challengeId: string) => acmeApi.verifyDnsChallenge(challengeId),
    onSuccess: (res) => {
      setVerifyResult({ success: res.data.success, message: res.data.message })
      if (res.data.success) {
        queryClient.invalidateQueries({ queryKey: ['proxy-routes'] })
        queryClient.invalidateQueries({ queryKey: ['proxy-certificates'] })
        toast({ title: 'Certificado emitido com sucesso!' })
      }
      setIsVerifying(false)
    },
    onError: (error: Error & { response?: { data?: { detail?: string; message?: string; details?: Array<{ msg?: string }> } } }) => {
      setVerifyResult({ success: false, message: getErrorMessage(error) })
      setIsVerifying(false)
    },
  })

  const handleRequestDns = (route: ProxyRoute) => {
    setDnsRouteContext(route)
    setDnsChallenge(null)
    setVerifyResult(null)
    setIsVerifying(false)
    setIsDnsDialogOpen(true)
    requestDnsMutation.mutate({ domain: route.hostname, proxy_route_id: route.id })
  }

  const handleVerifyDns = () => {
    if (!dnsChallenge) return
    setIsVerifying(true)
    setVerifyResult(null)
    verifyDnsMutation.mutate(dnsChallenge.id)
  }

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text)
    toast({ title: `${label} copiado para a área de transferência` })
  }

  const routes: ProxyRoute[] = routesData?.items || []

  const updateField = (field: keyof RouteForm, value: string | boolean) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  const formToPayload = (form: RouteForm): ProxyRouteCreate => {
    const payload: ProxyRouteCreate = {
      name: form.name,
      hostname: form.hostname,
      backend_url: form.backend_url,
      path_prefix: form.path_prefix || undefined,
      strip_prefix: form.strip_prefix,
      ssl_mode: form.ssl_mode as ProxyRouteCreate['ssl_mode'],
      force_https: form.force_https,
      health_check_type: form.health_check_type as ProxyRouteCreate['health_check_type'],
      health_check_path: form.health_check_path || '/',
      health_check_interval: form.health_check_interval || '30s',
      pass_host_header: form.pass_host_header,
      is_enabled: form.is_enabled,
    }
    if (form.custom_request_headers) payload.custom_request_headers = form.custom_request_headers
    if (form.custom_response_headers) payload.custom_response_headers = form.custom_response_headers
    if (form.rate_limit_average) payload.rate_limit_average = parseInt(form.rate_limit_average)
    if (form.rate_limit_burst) payload.rate_limit_burst = parseInt(form.rate_limit_burst)
    return payload
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim() || !formData.hostname.trim() || !formData.backend_url.trim()) {
      toast({ variant: 'destructive', title: 'Nome, hostname e URL do backend são obrigatórios' })
      return
    }
    createMutation.mutate(formToPayload(formData))
  }

  const handleEdit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingRoute) return
    const payload = formToPayload(formData) as unknown as Record<string, unknown>
    // Explicitly include path_prefix (even as null) so the backend can clear it
    payload.path_prefix = formData.path_prefix || null
    updateMutation.mutate({
      id: editingRoute.id,
      data: payload as Partial<ProxyRoute>,
    })
  }

  const handleToggleEnabled = (route: ProxyRoute) => {
    updateMutation.mutate({ id: route.id, data: { is_enabled: !route.is_enabled } })
  }

  const openEditModal = (route: ProxyRoute) => {
    setEditingRoute(route)
    setFormData({
      name: route.name,
      hostname: route.hostname,
      backend_url: route.backend_url,
      path_prefix: route.path_prefix || '',
      strip_prefix: route.strip_prefix,
      ssl_mode: route.ssl_mode,
      force_https: route.force_https,
      health_check_type: route.health_check_type,
      health_check_path: route.health_check_path || '/',
      health_check_interval: route.health_check_interval || '30s',
      pass_host_header: route.pass_host_header,
      custom_request_headers: route.custom_request_headers || '',
      custom_response_headers: route.custom_response_headers || '',
      rate_limit_average: route.rate_limit_average?.toString() || '',
      rate_limit_burst: route.rate_limit_burst?.toString() || '',
      is_enabled: route.is_enabled,
    })
    setIsEditModalOpen(true)
  }

  const openAddModal = () => {
    setFormData(createInitialForm())
    setIsAddModalOpen(true)
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-success/20 text-success">
            <CheckCircle2 className="h-3 w-3" /> Ativo
          </span>
        )
      case 'error':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-destructive/20 text-destructive">
            <XCircle className="h-3 w-3" /> Erro
          </span>
        )
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-warning/20 text-warning">
            <AlertCircle className="h-3 w-3" /> Pendente
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-muted text-muted-foreground">
            <AlertCircle className="h-3 w-3" /> Inativo
          </span>
        )
    }
  }

  const getHealthBadge = (route: ProxyRoute) => {
    if (route.last_health_status === null || route.last_health_status === undefined) {
      return <span className="text-xs text-muted-foreground">Não verificado</span>
    }
    if (route.last_health_status) {
      return (
        <span className="inline-flex items-center gap-1 text-xs text-success">
          <CheckCircle2 className="h-3 w-3" /> Saudável
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 text-xs text-destructive" title={route.last_error || ''}>
        <XCircle className="h-3 w-3" /> Não saudável
      </span>
    )
  }

  const renderFormFields = (prefix: string) => (
    <div className="space-y-6 mt-4">
      {/* Basic Info */}
      <div className="space-y-4">
        <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Detalhes da Rota</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-name`}>Nome da Rota *</Label>
            <Input
              id={`${prefix}-name`}
              value={formData.name}
              onChange={(e) => updateField('name', e.target.value)}
              placeholder="my-app"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-hostname`}>Hostname *</Label>
            <Input
              id={`${prefix}-hostname`}
              value={formData.hostname}
              onChange={(e) => updateField('hostname', e.target.value)}
              placeholder="app.domain.local"
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-backend_url`}>URL do Backend *</Label>
          <Input
            id={`${prefix}-backend_url`}
            value={formData.backend_url}
            onChange={(e) => updateField('backend_url', e.target.value)}
            placeholder="http://10.0.1.5:8080"
          />
          <p className="text-xs text-muted-foreground">URL do serviço de backend (EC2 privado, serviço interno, etc.)</p>
        </div>
      </div>

      {/* SSL */}
      <div className="space-y-4">
        <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">SSL / TLS</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-ssl_mode`}>Modo SSL</Label>
            <Select
              id={`${prefix}-ssl_mode`}
              value={formData.ssl_mode}
              onChange={(e) => updateField('ssl_mode', e.target.value)}
              options={SSL_MODE_OPTIONS}
            />
          </div>
          <div className="flex items-end pb-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.force_https}
                onChange={(e) => updateField('force_https', e.target.checked)}
                className="rounded"
              />
              <span className="text-sm">Forçar redirecionamento HTTPS</span>
            </label>
          </div>
        </div>
      </div>

      {/* Health Check */}
      <div className="space-y-4">
        <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Verificação de Saúde</h3>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-health_check_type`}>Tipo</Label>
            <Select
              id={`${prefix}-health_check_type`}
              value={formData.health_check_type}
              onChange={(e) => updateField('health_check_type', e.target.value)}
              options={HEALTH_CHECK_OPTIONS}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-health_check_path`}>Caminho</Label>
            <Input
              id={`${prefix}-health_check_path`}
              value={formData.health_check_path}
              onChange={(e) => updateField('health_check_path', e.target.value)}
              placeholder="/health"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-health_check_interval`}>Intervalo</Label>
            <Input
              id={`${prefix}-health_check_interval`}
              value={formData.health_check_interval}
              onChange={(e) => updateField('health_check_interval', e.target.value)}
              placeholder="30s"
            />
          </div>
        </div>
      </div>

      {/* Rate Limiting */}
      <div className="space-y-4">
        <h3 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Limitação de Taxa (Opcional)</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-rate_limit_average`}>Média (req/s)</Label>
            <Input
              id={`${prefix}-rate_limit_average`}
              type="number"
              value={formData.rate_limit_average}
              onChange={(e) => updateField('rate_limit_average', e.target.value)}
              placeholder="100"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-rate_limit_burst`}>Pico</Label>
            <Input
              id={`${prefix}-rate_limit_burst`}
              type="number"
              value={formData.rate_limit_burst}
              onChange={(e) => updateField('rate_limit_burst', e.target.value)}
              placeholder="200"
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
              checked={formData.pass_host_header}
              onChange={(e) => updateField('pass_host_header', e.target.checked)}
              className="rounded"
            />
            <span className="text-sm">Repassar cabeçalho Host</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={formData.is_enabled}
              onChange={(e) => updateField('is_enabled', e.target.checked)}
              className="rounded"
            />
            <span className="text-sm">Ativado</span>
          </label>
        </div>
      </div>
    </div>
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="Proxy Reverso"
        subtitle="Rotas, domínios e certificados"
        actions={
          <>
            <Button variant="outline" onClick={() => setIsConfigPreviewOpen(true)}>
              <Eye className="h-4 w-4 mr-2" />
              Visualizar Configuração
            </Button>
            <Button
              variant="outline"
              onClick={() => applyMutation.mutate()}
              disabled={applyMutation.isPending}
            >
              <Settings className="h-4 w-4 mr-2" />
              Aplicar Configuração
            </Button>
            <Button onClick={openAddModal}>
              <Plus className="h-4 w-4 mr-2" />
              Adicionar Rota
            </Button>
          </>
        }
      />

      {/* Traefik Status Card */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Globe className="h-4 w-4" />
              Traefik
            </CardTitle>
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                traefikStatus?.running
                  ? 'bg-success/20 text-success'
                  : 'bg-destructive/20 text-destructive'
              }`}>
                <span className={`h-2 w-2 rounded-full ${traefikStatus?.running ? 'bg-success' : 'bg-destructive'}`} />
                {traefikStatus?.running ? 'Em execução' : 'Parado'}
              </span>
              <span className="text-sm text-muted-foreground">
                {routes.length} rota{routes.length !== 1 ? 's' : ''}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => healthCheckMutation.mutate()}
                disabled={healthCheckMutation.isPending}
              >
                <Heart className={`h-4 w-4 mr-1 ${healthCheckMutation.isPending ? 'animate-pulse' : ''}`} />
                Verificar Saúde
              </Button>
              <Button variant="ghost" size="sm" onClick={() => refetchStatus()}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Routes Table */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="h-4 w-4" />
            Rotas de Proxy
          </CardTitle>
          <CardDescription className="text-xs">
            {routes.length} rota{routes.length !== 1 ? 's' : ''} configurada{routes.length !== 1 ? 's' : ''}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : routes.length === 0 ? (
            <div className="text-center py-8">
              <Globe className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <p className="text-muted-foreground mb-4">Nenhuma rota de proxy configurada</p>
              <Button onClick={openAddModal}>
                <Plus className="h-4 w-4 mr-2" />
                Adicionar Sua Primeira Rota
              </Button>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-3 text-left">Nome</th>
                    <th className="px-4 py-3 text-left">Hostname</th>
                    <th className="px-4 py-3 text-left">URL do Backend</th>
                    <th className="px-4 py-3 text-left">SSL</th>
                    <th className="px-4 py-3 text-left">Saúde</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {routes.map((route) => (
                    <tr key={route.id} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3">
                        <p className="font-medium">{route.name}</p>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{route.hostname}</td>
                      <td className="px-4 py-3 font-mono text-xs max-w-[200px] truncate" title={route.backend_url}>
                        {route.backend_url}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs capitalize">{route.ssl_mode.replace('_', ' ')}</span>
                      </td>
                      <td className="px-4 py-3">{getHealthBadge(route)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {getStatusBadge(route.status)}
                          <button
                            onClick={() => handleToggleEnabled(route)}
                            disabled={updateMutation.isPending}
                            className="p-1 rounded hover:bg-muted"
                            title={route.is_enabled ? 'Desativar' : 'Ativar'}
                          >
                            {route.is_enabled ? (
                              <Shield className="h-3.5 w-3.5 text-success" />
                            ) : (
                              <ShieldOff className="h-3.5 w-3.5 text-muted-foreground" />
                            )}
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {route.ssl_mode === 'letsencrypt_dns' && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleRequestDns(route)}
                              title="Solicitar Certificado DNS-01"
                            >
                              <FileKey className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => singleHealthCheckMutation.mutate(route.id)}
                            disabled={singleHealthCheckMutation.isPending}
                            title="Verificar saúde"
                          >
                            <Heart className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => openEditModal(route)} title="Editar rota">
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => deleteMutation.mutate(route.id)}
                            disabled={deleteMutation.isPending}
                            className="text-destructive hover:text-destructive"
                            title="Excluir rota"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* SSL Certificates Card */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Lock className="h-4 w-4" />
              Certificados SSL
            </CardTitle>
            <Button variant="ghost" size="sm" onClick={() => refetchCerts()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
          <CardDescription className="text-xs">
            {certsData?.acme_email && (
              <span>Conta ACME: {certsData.acme_email} &middot; </span>
            )}
            {certsData?.total || 0} certificado{(certsData?.total || 0) !== 1 ? 's' : ''}
            {(certsData?.valid || 0) > 0 && (
              <span className="text-success ml-2">{certsData?.valid} válido{(certsData?.valid || 0) !== 1 ? 's' : ''}</span>
            )}
            {(certsData?.expiring || 0) > 0 && (
              <span className="text-warning ml-2">{certsData?.expiring} expirando</span>
            )}
            {(certsData?.expired || 0) > 0 && (
              <span className="text-destructive ml-2">{certsData?.expired} expirado{(certsData?.expired || 0) !== 1 ? 's' : ''}</span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {!certsData || certsData.total === 0 ? (
            <div className="text-center py-6">
              <Lock className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <p className="text-muted-foreground text-sm">
                Nenhum certificado ainda. Os certificados são emitidos automaticamente quando você cria rotas com SSL ativado e aplica a configuração.
              </p>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-3 text-left">Domínio</th>
                    <th className="px-4 py-3 text-left">Emissor</th>
                    <th className="px-4 py-3 text-left">Expira em</th>
                    <th className="px-4 py-3 text-left">Restante</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {certsData.certificates.map((cert) => (
                    <tr key={cert.domain} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3">
                        <div>
                          <p className="font-medium font-mono text-xs">{cert.domain}</p>
                          {cert.sans && cert.sans.length > 0 && (
                            <p className="text-xs text-muted-foreground">
                              SANs: {cert.sans.join(', ')}
                            </p>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs">{cert.issuer || '-'}</td>
                      <td className="px-4 py-3 text-xs font-mono">
                        {cert.not_after ? formatDateTime(cert.not_after, { dateOnly: true }) : '-'}
                      </td>
                      <td className="px-4 py-3">
                        {cert.days_remaining !== null && cert.days_remaining !== undefined ? (
                          <span className={`text-xs font-medium ${
                            cert.days_remaining < 0
                              ? 'text-destructive'
                              : cert.days_remaining < 14
                              ? 'text-warning'
                              : 'text-success'
                          }`}>
                            {cert.days_remaining < 0
                              ? `Expirado há ${Math.abs(cert.days_remaining)}d`
                              : `${cert.days_remaining}d`}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {cert.status === 'valid' && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-success/20 text-success">
                            <CheckCircle2 className="h-3 w-3" /> Válido
                          </span>
                        )}
                        {cert.status === 'expiring' && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-warning/20 text-warning">
                            <AlertCircle className="h-3 w-3" /> Expirando
                          </span>
                        )}
                        {cert.status === 'expired' && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-destructive/20 text-destructive">
                            <XCircle className="h-3 w-3" /> Expirado
                          </span>
                        )}
                        {cert.status === 'error' && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-destructive/20 text-destructive">
                            <XCircle className="h-3 w-3" /> Erro
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => renewCertMutation.mutate(cert.domain)}
                            disabled={renewCertMutation.isPending}
                            title={`Forçar renovação de ${cert.domain}`}
                          >
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              if (confirm(`Excluir certificado de ${cert.domain}?`)) {
                                deleteCertMutation.mutate(cert.domain)
                              }
                            }}
                            disabled={deleteCertMutation.isPending}
                            className="text-destructive hover:text-destructive"
                            title={`Excluir certificado de ${cert.domain}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>


      {/* Add Route Modal */}
      <Dialog open={isAddModalOpen} onOpenChange={setIsAddModalOpen}>
        <DialogContent onClose={() => setIsAddModalOpen(false)} className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Adicionar Rota de Proxy</DialogTitle>
            <DialogDescription>Configure uma nova rota de proxy reverso para um serviço externo</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate}>
            {renderFormFields("add")}
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsAddModalOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Criando...' : 'Criar Rota'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit Route Modal */}
      <Dialog open={isEditModalOpen} onOpenChange={setIsEditModalOpen}>
        <DialogContent onClose={() => setIsEditModalOpen(false)} className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Editar Rota de Proxy</DialogTitle>
            <DialogDescription>Modifique a configuração da rota de proxy</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEdit}>
            {renderFormFields("edit")}
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsEditModalOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? 'Salvando...' : 'Salvar Alterações'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DNS-01 Challenge Dialog */}
      <Dialog open={isDnsDialogOpen} onOpenChange={setIsDnsDialogOpen}>
        <DialogContent onClose={() => setIsDnsDialogOpen(false)} className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileKey className="h-5 w-5" />
              Desafio de Certificado DNS-01
            </DialogTitle>
            <DialogDescription>
              {dnsRouteContext?.hostname && (
                <span>Solicitar um certificado Let's Encrypt para <strong className="font-mono">{dnsRouteContext.hostname}</strong></span>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 mt-2">
            {requestDnsMutation.isPending && (
              <div className="flex items-center justify-center py-8 gap-2 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>Solicitando desafio ao Let's Encrypt...</span>
              </div>
            )}

            {dnsChallenge && (
              <>
                <div className="rounded-lg bg-muted p-4 space-y-4">
                  <p className="text-sm font-medium">Adicione o seguinte registro TXT ao seu DNS:</p>

                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Nome do Registro TXT</Label>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 px-3 py-2 bg-background rounded text-sm font-mono break-all">
                        {dnsChallenge.txt_record_name}
                      </code>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => copyToClipboard(dnsChallenge.txt_record_name || '', 'Nome do registro TXT')}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Valor do Registro TXT</Label>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 px-3 py-2 bg-background rounded text-sm font-mono break-all">
                        {dnsChallenge.txt_record_value}
                      </code>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => copyToClipboard(dnsChallenge.txt_record_value || '', 'Valor do registro TXT')}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border p-4 space-y-2">
                  <p className="text-sm font-medium">Passos:</p>
                  <ol className="text-sm text-muted-foreground space-y-1 list-decimal list-inside">
                    <li>Acesse o painel de controle do seu provedor de DNS</li>
                    <li>Adicione um registro TXT com o nome e o valor acima</li>
                    <li>Aguarde a propagação do DNS (pode levar alguns minutos)</li>
                    <li>Clique em "Verificar e Emitir" abaixo</li>
                  </ol>
                  <div className="mt-3 pt-3 border-t">
                    <p className="text-xs text-muted-foreground">
                      Para verificar a propagação, execute:{' '}
                      <code className="px-1.5 py-0.5 bg-muted rounded text-xs font-mono">
                        dig TXT {dnsChallenge.txt_record_name}
                      </code>
                    </p>
                  </div>
                </div>

                {verifyResult && (
                  <div className={`rounded-lg p-3 text-sm ${
                    verifyResult.success
                      ? 'bg-success/10 text-success border border-success/20'
                      : 'bg-destructive/10 text-destructive border border-destructive/20'
                  }`}>
                    <div className="flex items-center gap-2">
                      {verifyResult.success ? (
                        <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                      ) : (
                        <XCircle className="h-4 w-4 flex-shrink-0" />
                      )}
                      <span>{verifyResult.message}</span>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          <DialogFooter className="mt-4">
            <Button variant="outline" onClick={() => setIsDnsDialogOpen(false)}>
              {verifyResult?.success ? 'Concluído' : 'Cancelar'}
            </Button>
            {dnsChallenge && !verifyResult?.success && (
              <Button
                onClick={handleVerifyDns}
                disabled={isVerifying}
              >
                {isVerifying ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Verificando...
                  </>
                ) : (
                  'Verificar e Emitir Certificado'
                )}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Config Preview Modal */}
      <Dialog open={isConfigPreviewOpen} onOpenChange={setIsConfigPreviewOpen}>
        <DialogContent onClose={() => setIsConfigPreviewOpen(false)} className="max-w-3xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle>Visualização da Configuração</DialogTitle>
            <DialogDescription>Visualização do YAML dinâmico gerado do Traefik (routes.yml)</DialogDescription>
          </DialogHeader>
          <div className="mt-4">
            <pre className="p-4 bg-muted rounded-lg text-xs overflow-auto max-h-[60vh] font-mono">
              {configPreview?.yaml_config || 'Carregando...'}
            </pre>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsConfigPreviewOpen(false)}>Fechar</Button>
            <Button onClick={() => applyMutation.mutate()} disabled={applyMutation.isPending}>
              {applyMutation.isPending ? 'Aplicando...' : 'Aplicar Configuração'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
