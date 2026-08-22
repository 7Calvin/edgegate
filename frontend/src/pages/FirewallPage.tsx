import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, firewallApi } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import { formatDateTime } from '@/lib/tz'
import { Shield, ShieldOff, Trash2, Zap, Users, Network, GripVertical, Plus, ArrowRight, Server, Pencil, RefreshCw, Globe, Check, X } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import type { FirewallRule } from '@/types'

interface QuickRuleStatus {
  exists: boolean
  is_active: boolean
  id: string | null
  description: string
  networks?: string[]
}

interface QuickRulesResponse {
  [key: string]: QuickRuleStatus
}

interface NewRuleForm {
  name: string
  description: string
  action: string
  protocol: string
  source_network: string
  destination_network: string
  destination_port_range: string
  priority: number
}

interface NATRule {
  id: string
  name: string
  description?: string
  nat_type: string
  protocol: string
  external_port: number
  internal_ip: string
  internal_port: number
  source_network?: string
  is_active: boolean
  created_at: string
}

interface NewDNATForm {
  name: string
  description: string
  protocol: string
  external_port: string
  internal_ip: string
  internal_port: string
  source_network: string
}

const QUICK_RULE_CONFIG: Record<string, { label: string; subtitle: string; icon: React.ElementType; color: string }> = {
  'block-client-to-client': {
    label: 'Bloquear Cliente-a-Cliente',
    subtitle: 'Impede que os clientes VPN se comuniquem entre si',
    icon: Users,
    color: 'text-destructive',
  },
  'allow-internal-network': {
    label: 'Permitir Acesso à Rede Privada',
    subtitle: 'Permite que os clientes VPN alcancem a sub-rede privada atrás deste servidor',
    icon: Network,
    color: 'text-success',
  },
}

const ACTION_OPTIONS = [
  { value: 'accept', label: 'Accept - Permitir tráfego' },
  { value: 'drop', label: 'Drop - Descartar silenciosamente' },
  { value: 'reject', label: 'Reject - Descartar com resposta' },
  { value: 'limit', label: 'Limit - Limitar taxa de tráfego' },
]

const PROTOCOL_OPTIONS = [
  { value: 'all', label: 'Todos os Protocolos' },
  { value: 'tcp', label: 'TCP' },
  { value: 'udp', label: 'UDP' },
  { value: 'icmp', label: 'ICMP' },
]

const DNAT_PROTOCOL_OPTIONS = [
  { value: 'tcp', label: 'TCP' },
  { value: 'udp', label: 'UDP' },
]

// Common service presets for DNAT wizard
const SERVICE_PRESETS = [
  { name: 'HTTP', port: 80, protocol: 'tcp' },
  { name: 'HTTPS', port: 443, protocol: 'tcp' },
  { name: 'SSH', port: 22, protocol: 'tcp' },
  { name: 'RDP', port: 3389, protocol: 'tcp' },
  { name: 'MySQL', port: 3306, protocol: 'tcp' },
  { name: 'PostgreSQL', port: 5432, protocol: 'tcp' },
  { name: 'Redis', port: 6379, protocol: 'tcp' },
  { name: 'MongoDB', port: 27017, protocol: 'tcp' },
]

const initialFormState: NewRuleForm = {
  name: '',
  description: '',
  action: 'accept',
  protocol: 'all',
  source_network: '',
  destination_network: '',
  destination_port_range: '',
  priority: 100,
}

const initialDNATFormState: NewDNATForm = {
  name: '',
  description: '',
  protocol: 'tcp',
  external_port: '',
  internal_ip: '',
  internal_port: '',
  source_network: '*',
}

export default function FirewallPage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isDNATModalOpen, setIsDNATModalOpen] = useState(false)
  const [newRule, setNewRule] = useState<NewRuleForm>(initialFormState)
  const [newDNAT, setNewDNAT] = useState<NewDNATForm>(initialDNATFormState)
  const [isEditDNATModalOpen, setIsEditDNATModalOpen] = useState(false)
  const [editingDNAT, setEditingDNAT] = useState<NATRule | null>(null)
  const [editDNATForm, setEditDNATForm] = useState<NewDNATForm>(initialDNATFormState)
  const [natToDelete, setNatToDelete] = useState<NATRule | null>(null)

  const { data: rules, isLoading } = useQuery({
    queryKey: ['firewall-rules'],
    queryFn: () => firewallApi.listRules().then((res) => res.data),
  })

  const { data: status } = useQuery({
    queryKey: ['firewall-status'],
    queryFn: () => firewallApi.getStatus().then((res) => res.data),
  })

  const { data: quickRules } = useQuery<QuickRulesResponse>({
    queryKey: ['firewall-quick-rules'],
    queryFn: () => firewallApi.getQuickRules().then((res) => res.data),
  })

  // Editable networks for the "allow-internal-network" quick rule. Prefilled
  // from the server (current rule networks, or the default from push routes).
  const [internalNets, setInternalNets] = useState('')
  useEffect(() => {
    const nets = quickRules?.['allow-internal-network']?.networks
    if (nets) setInternalNets(nets.join(', '))
  }, [quickRules])
  const parseNets = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

  const { data: natRules, isLoading: isLoadingNAT } = useQuery<NATRule[]>({
    queryKey: ['nat-rules'],
    queryFn: () => firewallApi.listNatRules().then((res) => res.data),
  })

  // Helper to apply rules after changes
  const applyRulesAfterChange = async () => {
    try {
      await firewallApi.apply()
      queryClient.invalidateQueries({ queryKey: ['firewall-status'] })
    } catch {
      // Silent fail - rules are saved, just not applied to nftables
    }
  }

  const [confirmReapply, setConfirmReapply] = useState(false)
  // NAT Gateway (host-as-NAT) — rendered as a row inside Regras Rápidas
  const { data: natGw, refetch: refetchNat } = useQuery({
    queryKey: ['nat-gateway'],
    queryFn: () => adminApi.getNatGateway().then((r) => r.data),
  })
  const natSaveMutation = useMutation({
    mutationFn: (payload: { enabled: boolean; network: string }) =>
      adminApi.updateNatGateway({
        enabled: payload.enabled,
        network: payload.network || null,
        public_interface: null,
        exclude_networks: null,
      }),
    onSuccess: (res: any) => {
      toast({
        title: 'NAT Gateway atualizado',
        description: res?.data?.applied === false ? 'Salvo, mas o agente não aplicou.' : 'Regras aplicadas.',
      })
      refetchNat()
    },
    onError: (error: any) =>
      toast({ variant: 'destructive', title: 'Falha no NAT Gateway', description: error?.response?.data?.detail || error?.response?.data?.message }),
  })

  // Shared "gray value + pencil → inline edit/save" for the rule rows.
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const startEdit = (field: string, current: string) => { setEditingField(field); setEditValue(current) }
  const renderEditable = (
    field: string, value: string, placeholder: string,
    onSave: (v: string) => void, pending: boolean,
  ) => {
    if (editingField === field) {
      return (
        <div className="flex items-center gap-1">
          <Input
            autoFocus
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); onSave(editValue); setEditingField(null) }
              else if (e.key === 'Escape') setEditingField(null)
            }}
            placeholder={placeholder}
            className="h-8 w-48 font-mono text-xs"
          />
          <Button variant="ghost" size="sm" className="h-7 px-2" disabled={pending}
            onClick={() => { onSave(editValue); setEditingField(null) }}>
            <Check className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => setEditingField(null)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )
    }
    return (
      <button
        onClick={() => startEdit(field, value)}
        className="group flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <span className="font-mono truncate max-w-[180px]">{value || '—'}</span>
        <Pencil className="h-3.5 w-3.5 opacity-50 group-hover:opacity-100" />
      </button>
    )
  }

  const reapplyMutation = useMutation({
    mutationFn: () => firewallApi.apply(),
    onSuccess: () => {
      setConfirmReapply(false)
      queryClient.invalidateQueries({ queryKey: ['firewall-status'] })
      toast({ title: 'Regras reaplicadas', description: 'As regras foram reaplicadas no firewall.' })
    },
    onError: (error: any) => {
      setConfirmReapply(false)
      toast({ variant: 'destructive', title: 'Falha ao reaplicar', description: error?.response?.data?.detail })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => firewallApi.deleteRule(id),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-quick-rules'] })
      toast({ title: 'Regra excluída' })
      await applyRulesAfterChange()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao excluir regra' })
    },
  })

  const toggleRuleMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      firewallApi.updateRule(id, { is_active: isActive }),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-quick-rules'] })
      toast({ title: 'Status da regra atualizado' })
      await applyRulesAfterChange()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao atualizar regra' })
    },
  })

  const updatePriorityMutation = useMutation({
    mutationFn: ({ id, priority }: { id: string; priority: number }) =>
      firewallApi.updateRule(id, { priority }),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Ordem das regras atualizada' })
      await applyRulesAfterChange()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao atualizar ordem' })
    },
  })

  const quickRuleToggleMutation = useMutation({
    mutationFn: ({ key, networks }: { key: string; networks?: string[] }) =>
      firewallApi.toggleQuickRule(key, networks),
    onSuccess: async (_, { key }) => {
      queryClient.invalidateQueries({ queryKey: ['firewall-quick-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      const config = QUICK_RULE_CONFIG[key]
      toast({ title: `${config?.label || key} alternada` })
      await applyRulesAfterChange()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao alternar regra' })
    },
  })

  const setNetworksMutation = useMutation({
    mutationFn: (networks: string[]) =>
      firewallApi.setQuickRuleNetworks('allow-internal-network', networks),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['firewall-quick-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Redes atualizadas' })
      await applyRulesAfterChange()
    },
    onError: (e: any) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao salvar redes',
        description: e?.response?.data?.detail,
      })
    },
  })

  const createRuleMutation = useMutation({
    mutationFn: (data: NewRuleForm) => {
      const payload: Record<string, unknown> = {
        name: data.name,
        description: data.description || undefined,
        action: data.action,
        protocol: data.protocol,
        priority: data.priority,
      }
      if (data.source_network) payload.source_network = data.source_network
      if (data.destination_network) payload.destination_network = data.destination_network
      if (data.destination_port_range) payload.destination_port_range = data.destination_port_range
      return firewallApi.createRule(payload as Parameters<typeof firewallApi.createRule>[0])
    },
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Regra criada com sucesso' })
      setIsAddModalOpen(false)
      setNewRule(initialFormState)
      await applyRulesAfterChange()
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao criar regra',
        description: error.response?.data?.detail || 'Erro desconhecido',
      })
    },
  })

  const createDNATMutation = useMutation({
    mutationFn: (data: NewDNATForm) => {
      const sourceNet = data.source_network.trim()
      return firewallApi.createNatRule({
        name: data.name,
        description: data.description || undefined,
        protocol: data.protocol,
        external_port: parseInt(data.external_port),
        internal_ip: data.internal_ip,
        internal_port: parseInt(data.internal_port),
        source_network: (sourceNet && sourceNet !== '*') ? sourceNet : undefined,
      })
    },
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['nat-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Regra de encaminhamento de porta criada' })
      setIsDNATModalOpen(false)
      setNewDNAT(initialDNATFormState)
      await applyRulesAfterChange()
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao criar regra',
        description: error.response?.data?.detail || 'Erro desconhecido',
      })
    },
  })

  const toggleNATMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      firewallApi.updateNatRule(id, { is_active: isActive }),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['nat-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Status da regra NAT atualizado' })
      await applyRulesAfterChange()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao atualizar regra' })
    },
  })

  const deleteNATMutation = useMutation({
    mutationFn: (id: string) => firewallApi.deleteNatRule(id),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['nat-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Regra NAT excluída' })
      setNatToDelete(null)
      await applyRulesAfterChange()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao excluir regra' })
    },
  })

  const updateDNATMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      firewallApi.updateNatRule(id, data),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['nat-rules'] })
      queryClient.invalidateQueries({ queryKey: ['firewall-rules'] })
      toast({ title: 'Regra NAT atualizada' })
      setIsEditDNATModalOpen(false)
      setEditingDNAT(null)
      await applyRulesAfterChange()
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao atualizar regra',
        description: error.response?.data?.detail || 'Erro desconhecido',
      })
    },
  })

  const openEditDNAT = (rule: NATRule) => {
    setEditingDNAT(rule)
    setEditDNATForm({
      name: rule.name,
      description: rule.description || '',
      protocol: rule.protocol,
      external_port: String(rule.external_port),
      internal_ip: rule.internal_ip,
      internal_port: String(rule.internal_port),
      source_network: rule.source_network || '*',
    })
    setIsEditDNATModalOpen(true)
  }

  const handleEditDNAT = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingDNAT) return
    const sourceNet = editDNATForm.source_network.trim()
    updateDNATMutation.mutate({
      id: editingDNAT.id,
      data: {
        name: editDNATForm.name,
        description: editDNATForm.description || null,
        protocol: editDNATForm.protocol,
        external_port: parseInt(editDNATForm.external_port),
        internal_ip: editDNATForm.internal_ip,
        internal_port: parseInt(editDNATForm.internal_port),
        source_network: (sourceNet && sourceNet !== '*') ? sourceNet : null,
      },
    })
  }

  const ruleList: FirewallRule[] = Array.isArray(rules) ? rules : rules?.items || []
  const sortedRules = [...ruleList].sort((a, b) => a.priority - b.priority)
  const natRuleList: NATRule[] = natRules || []

  const getActionColor = (action: string) => {
    switch (action) {
      case 'accept':
        return 'bg-success/20 text-success'
      case 'drop':
        return 'bg-destructive/20 text-destructive'
      case 'reject':
        return 'bg-orange-500/20 text-orange-500'
      case 'limit':
        return 'bg-warning/20 text-warning'
      default:
        return 'bg-muted text-muted-foreground'
    }
  }

  const handleDragStart = (e: React.DragEvent, ruleId: string) => {
    setDraggedId(ruleId)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDrop = (e: React.DragEvent, targetRule: FirewallRule) => {
    e.preventDefault()
    if (!draggedId || draggedId === targetRule.id) {
      setDraggedId(null)
      return
    }

    const draggedRule = sortedRules.find((r) => r.id === draggedId)
    if (!draggedRule) {
      setDraggedId(null)
      return
    }

    const targetIndex = sortedRules.findIndex((r) => r.id === targetRule.id)
    const draggedIndex = sortedRules.findIndex((r) => r.id === draggedId)

    let newPriority: number
    if (targetIndex === 0) {
      newPriority = Math.max(1, targetRule.priority - 1)
    } else if (targetIndex === sortedRules.length - 1) {
      newPriority = targetRule.priority + 1
    } else {
      if (draggedIndex < targetIndex) {
        const nextRule = sortedRules[targetIndex + 1]
        newPriority = Math.floor((targetRule.priority + (nextRule?.priority || targetRule.priority + 2)) / 2)
      } else {
        const prevRule = sortedRules[targetIndex - 1]
        newPriority = Math.floor(((prevRule?.priority || 0) + targetRule.priority) / 2)
      }
    }

    if (newPriority === targetRule.priority) {
      newPriority = draggedIndex < targetIndex ? targetRule.priority + 1 : targetRule.priority
    }

    updatePriorityMutation.mutate({ id: draggedId, priority: newPriority })
    setDraggedId(null)
  }

  const handleDragEnd = () => {
    setDraggedId(null)
  }

  const handleCreateRule = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newRule.name.trim()) {
      toast({ variant: 'destructive', title: 'O nome da regra é obrigatório' })
      return
    }
    createRuleMutation.mutate(newRule)
  }

  const handleCreateDNAT = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newDNAT.name.trim()) {
      toast({ variant: 'destructive', title: 'O nome da regra é obrigatório' })
      return
    }
    if (!newDNAT.external_port || !newDNAT.internal_ip || !newDNAT.internal_port) {
      toast({ variant: 'destructive', title: 'Todos os campos de porta e IP são obrigatórios' })
      return
    }
    createDNATMutation.mutate(newDNAT)
  }

  const applyServicePreset = (preset: typeof SERVICE_PRESETS[0]) => {
    setNewDNAT({
      ...newDNAT,
      name: `forward-${preset.name.toLowerCase()}`,
      description: `Encaminhar ${preset.name} para servidor interno`,
      protocol: preset.protocol,
      external_port: String(preset.port),
      internal_port: String(preset.port),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Firewall"
        subtitle="Regras de acesso da VPN"
        actions={
          <Button variant="outline" onClick={() => setConfirmReapply(true)}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Reaplicar regras
          </Button>
        }
      />

      {/* Status strip */}
      {status && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg border border-border bg-card px-4 py-2.5 text-sm">
          <span className="flex items-center gap-2 font-medium">
            <Shield className={`h-4 w-4 ${status.is_active ? 'text-success' : 'text-destructive'}`} />
            Firewall {status.is_active ? 'ativo' : 'inativo'}
          </span>
          <span className="hidden h-4 w-px bg-border sm:block" aria-hidden />
          <span className="text-muted-foreground">
            Motor <span className="text-foreground">{status.engine || 'nftables'}</span>
          </span>
          <span className="text-muted-foreground">
            Regras <span className="text-foreground">{status.active_rules || 0}</span>
          </span>
          <span className="text-muted-foreground">
            Última aplicação{' '}
            <span className="text-foreground">
              {status.last_applied ? formatDateTime(status.last_applied) : 'nunca'}
            </span>
          </span>
        </div>
      )}

      {/* Regras Rápidas + NAT Gateway — uma linha por regra */}
      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Zap className="h-4 w-4" />
            Regras Rápidas
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          <div className="divide-y divide-border">
            {Object.entries(QUICK_RULE_CONFIG).map(([key, config]) => {
              const isEnabled = quickRules?.[key]?.exists || false
              const Icon = config.icon
              const editable = key === 'allow-internal-network'
              return (
                <div key={key} className="flex items-center gap-3 py-2.5">
                  <Icon className={`h-4 w-4 shrink-0 ${isEnabled ? config.color : 'text-muted-foreground'}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{config.label}</p>
                    <p className="text-xs text-muted-foreground truncate">{config.subtitle}</p>
                  </div>
                  {editable && renderEditable(
                    'internal-nets', internalNets, '10.10.22.0/24, 192.168.0.0/16',
                    (v) => { setInternalNets(v); setNetworksMutation.mutate(parseNets(v)) },
                    setNetworksMutation.isPending,
                  )}
                  <button
                    onClick={() => quickRuleToggleMutation.mutate({ key, networks: editable ? parseNets(internalNets) : undefined })}
                    disabled={quickRuleToggleMutation.isPending}
                    className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${isEnabled ? 'bg-primary' : 'bg-muted-foreground/30'}`}
                  >
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${isEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
                  </button>
                </div>
              )
            })}

            {/* NAT Gateway como linha */}
            <div className="flex items-center gap-3 py-2.5">
              <Globe className={`h-4 w-4 shrink-0 ${natGw?.enabled ? 'text-primary' : 'text-muted-foreground'}`} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">NAT Gateway (saída à internet)</p>
                <p className="text-xs text-muted-foreground truncate">Masquerade da sub-rede · interface e exceções IPsec automáticas</p>
              </div>
              {renderEditable(
                'nat-network', natGw?.network ?? '', '10.1.0.0/16',
                (v) => natSaveMutation.mutate({ enabled: natGw?.enabled ?? false, network: v }),
                natSaveMutation.isPending,
              )}
              <button
                onClick={() => natSaveMutation.mutate({ enabled: !(natGw?.enabled ?? false), network: natGw?.network ?? '' })}
                disabled={natSaveMutation.isPending || (!natGw?.enabled && !natGw?.network)}
                className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${natGw?.enabled ? 'bg-primary' : 'bg-muted-foreground/30'}`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${natGw?.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            Nota: clique em "Reaplicar regras" no topo para ativar mudanças de firewall.
          </p>
        </CardContent>
      </Card>

      {/* Port Forwarding (DNAT) */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between p-4 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="h-4 w-4" />
              Encaminhamento de Portas (DNAT)
            </CardTitle>
            <CardDescription className="text-xs">Portas externas → hosts internos na rede privada (via agente NAT)</CardDescription>
          </div>
          <Button size="sm" onClick={() => setIsDNATModalOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Adicionar
          </Button>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoadingNAT ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : natRuleList.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-muted-foreground mb-4">Nenhuma regra de encaminhamento de porta configurada</p>
              <Button variant="outline" onClick={() => setIsDNATModalOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Adicionar Sua Primeira Regra de Encaminhamento
              </Button>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-3 text-left">Nome</th>
                    <th className="px-4 py-3 text-left">Origem</th>
                    <th className="px-4 py-3 text-left">Porta Externa</th>
                    <th className="px-4 py-3 text-left"></th>
                    <th className="px-4 py-3 text-left">Destino Interno</th>
                    <th className="px-4 py-3 text-left">Protocolo</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {natRuleList.map((rule) => (
                    <tr key={rule.id} className="border-b hover:bg-muted/50">
                      <td className="px-4 py-3">
                        <p className="font-medium">{rule.name}</p>
                        {rule.description && (
                          <p className="text-xs text-muted-foreground">{rule.description}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {rule.source_network || <span className="text-muted-foreground">Qualquer (*)</span>}
                      </td>
                      <td className="px-4 py-3 font-mono">{rule.external_port}</td>
                      <td className="px-4 py-3">
                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                      </td>
                      <td className="px-4 py-3 font-mono">
                        {rule.internal_ip}:{rule.internal_port}
                      </td>
                      <td className="px-4 py-3 uppercase">{rule.protocol}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => toggleNATMutation.mutate({ id: rule.id, isActive: !rule.is_active })}
                          disabled={toggleNATMutation.isPending}
                          className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium transition-colors ${
                            rule.is_active
                              ? 'bg-success/20 text-success hover:bg-success/30'
                              : 'bg-muted text-muted-foreground hover:bg-muted/80'
                          }`}
                        >
                          {rule.is_active ? <Shield className="h-3 w-3" /> : <ShieldOff className="h-3 w-3" />}
                          {rule.is_active ? 'Ativo' : 'Inativo'}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditDNAT(rule)}
                            title="Editar regra"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setNatToDelete(rule)}
                            className="text-destructive hover:text-destructive"
                            title="Excluir regra"
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

      {/* Rules */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between p-4 pb-3">
          <div>
            <CardTitle className="text-base">Regras do Firewall</CardTitle>
            <CardDescription className="text-xs">{ruleList.length} regras no tráfego VPN — arraste para reordenar a prioridade</CardDescription>
          </div>
          <Button size="sm" onClick={() => setIsAddModalOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Adicionar Regra
          </Button>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : ruleList.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-muted-foreground">Nenhuma regra de firewall configurada</p>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b">
                  <tr>
                    <th className="px-2 py-3 text-left w-10"></th>
                    <th className="px-4 py-3 text-left">Prioridade</th>
                    <th className="px-4 py-3 text-left">Nome</th>
                    <th className="px-4 py-3 text-left">Descrição</th>
                    <th className="px-4 py-3 text-left">Ação</th>
                    <th className="px-4 py-3 text-left">Protocolo</th>
                    <th className="px-4 py-3 text-left">Destino</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRules.map((rule: FirewallRule) => (
                    <tr
                      key={rule.id}
                      className={`border-b transition-colors ${
                        draggedId === rule.id ? 'opacity-50 bg-muted' : 'hover:bg-muted/50'
                      }`}
                      draggable={!rule.is_system_rule}
                      onDragStart={(e) => handleDragStart(e, rule.id)}
                      onDragOver={handleDragOver}
                      onDrop={(e) => handleDrop(e, rule)}
                      onDragEnd={handleDragEnd}
                    >
                      <td className="px-2 py-3">
                        {!rule.is_system_rule && (
                          <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab" />
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono">{rule.priority}</td>
                      <td className="px-4 py-3 font-medium">{rule.name}</td>
                      <td className="px-4 py-3 text-sm text-muted-foreground">
                        {rule.description || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-1 rounded text-xs uppercase ${getActionColor(rule.action)}`}>
                          {rule.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 uppercase">{rule.protocol}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {rule.destination_network || 'qualquer'}
                        {rule.destination_port_range && `:${rule.destination_port_range}`}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => toggleRuleMutation.mutate({ id: rule.id, isActive: !rule.is_active })}
                          disabled={toggleRuleMutation.isPending}
                          className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium transition-colors ${
                            rule.is_active
                              ? 'bg-success/20 text-success hover:bg-success/30'
                              : 'bg-muted text-muted-foreground hover:bg-muted/80'
                          }`}
                        >
                          {rule.is_active ? <Shield className="h-3 w-3" /> : <ShieldOff className="h-3 w-3" />}
                          {rule.is_active ? 'Ativo' : 'Inativo'}
                        </button>
                        {rule.is_system_rule && (
                          <span className="ml-2 text-xs text-muted-foreground">(Sistema)</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => deleteMutation.mutate(rule.id)}
                          disabled={rule.is_system_rule}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Rule Modal */}
      <Dialog open={isAddModalOpen} onOpenChange={setIsAddModalOpen}>
        <DialogContent onClose={() => setIsAddModalOpen(false)} className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Adicionar Regra de Firewall</DialogTitle>
            <DialogDescription>
              Crie uma regra de firewall personalizada. Todos os campos, exceto o nome, são opcionais.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateRule} className="space-y-4 mt-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">Nome da Regra *</Label>
                <Input
                  id="name"
                  value={newRule.name}
                  onChange={(e) => setNewRule({ ...newRule, name: e.target.value })}
                  placeholder="minha-regra-personalizada"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="priority">Prioridade</Label>
                <Input
                  id="priority"
                  type="number"
                  min={1}
                  max={10000}
                  value={newRule.priority}
                  onChange={(e) => setNewRule({ ...newRule, priority: parseInt(e.target.value) || 100 })}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Descrição</Label>
              <Input
                id="description"
                value={newRule.description}
                onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
                placeholder="O que esta regra faz?"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="action">Ação</Label>
                <Select
                  id="action"
                  value={newRule.action}
                  onChange={(e) => setNewRule({ ...newRule, action: e.target.value })}
                  options={ACTION_OPTIONS}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="protocol">Protocolo</Label>
                <Select
                  id="protocol"
                  value={newRule.protocol}
                  onChange={(e) => setNewRule({ ...newRule, protocol: e.target.value })}
                  options={PROTOCOL_OPTIONS}
                />
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="source_network">Rede de Origem</Label>
                <Input
                  id="source_network"
                  value={newRule.source_network}
                  onChange={(e) => setNewRule({ ...newRule, source_network: e.target.value })}
                  placeholder="10.8.0.0/24 ou deixe vazio para qualquer"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="destination_network">Rede de Destino</Label>
                <Input
                  id="destination_network"
                  value={newRule.destination_network}
                  onChange={(e) => setNewRule({ ...newRule, destination_network: e.target.value })}
                  placeholder="192.168.1.0/24 ou deixe vazio para qualquer"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="destination_port_range">Porta(s) de Destino</Label>
              <Input
                id="destination_port_range"
                value={newRule.destination_port_range}
                onChange={(e) => setNewRule({ ...newRule, destination_port_range: e.target.value })}
                placeholder="80 ou 80,443 ou 8000-9000"
              />
              <p className="text-xs text-muted-foreground">
                Porta única, separadas por vírgula ou intervalo (ex.: 80, 80,443, 8000-9000)
              </p>
            </div>

            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsAddModalOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={createRuleMutation.isPending}>
                {createRuleMutation.isPending ? 'Criando...' : 'Criar Regra'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DNAT Wizard Modal */}
      <Dialog open={isDNATModalOpen} onOpenChange={setIsDNATModalOpen}>
        <DialogContent onClose={() => setIsDNATModalOpen(false)} className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Assistente de Encaminhamento de Portas</DialogTitle>
            <DialogDescription>
              Encaminhe o tráfego de uma porta externa para um servidor interno na sua rede privada.
            </DialogDescription>
          </DialogHeader>

          {/* Service Presets */}
          <div className="mt-4">
            <Label className="text-sm font-medium">Predefinições Rápidas</Label>
            <div className="flex flex-wrap gap-2 mt-2">
              {SERVICE_PRESETS.map((preset) => (
                <Button
                  key={preset.name}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => applyServicePreset(preset)}
                  className="text-xs"
                >
                  {preset.name} ({preset.port})
                </Button>
              ))}
            </div>
          </div>

          <form onSubmit={handleCreateDNAT} className="space-y-4 mt-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="dnat-name">Nome da Regra *</Label>
                <Input
                  id="dnat-name"
                  value={newDNAT.name}
                  onChange={(e) => setNewDNAT({ ...newDNAT, name: e.target.value })}
                  placeholder="forward-web-server"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dnat-protocol">Protocolo</Label>
                <Select
                  id="dnat-protocol"
                  value={newDNAT.protocol}
                  onChange={(e) => setNewDNAT({ ...newDNAT, protocol: e.target.value })}
                  options={DNAT_PROTOCOL_OPTIONS}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="dnat-description">Descrição</Label>
              <Input
                id="dnat-description"
                value={newDNAT.description}
                onChange={(e) => setNewDNAT({ ...newDNAT, description: e.target.value })}
                placeholder="Encaminhar para servidor web interno"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="dnat-source">IPs de Origem Permitidos</Label>
              <Input
                id="dnat-source"
                value={newDNAT.source_network}
                onChange={(e) => setNewDNAT({ ...newDNAT, source_network: e.target.value })}
                placeholder="* (qualquer)"
              />
              <p className="text-xs text-muted-foreground">
                Use <code className="px-1 bg-muted rounded">*</code> para qualquer origem, ou especifique IP/CIDR (ex.: <code className="px-1 bg-muted rounded">203.0.113.10</code> ou <code className="px-1 bg-muted rounded">10.0.0.0/24</code>)
              </p>
            </div>

            <div className="p-4 bg-muted/50 rounded-lg space-y-4">
              <div className="flex items-center gap-4">
                <div className="flex-1 space-y-2">
                  <Label htmlFor="external-port">Porta Externa *</Label>
                  <Input
                    id="external-port"
                    type="number"
                    min={1}
                    max={65535}
                    value={newDNAT.external_port}
                    onChange={(e) => setNewDNAT({ ...newDNAT, external_port: e.target.value })}
                    placeholder="8080"
                  />
                  <p className="text-xs text-muted-foreground">Porta exposta no servidor VPN</p>
                </div>

                <ArrowRight className="h-6 w-6 text-muted-foreground mt-2" />

                <div className="flex-1 space-y-2">
                  <Label htmlFor="internal-ip">IP Interno *</Label>
                  <Input
                    id="internal-ip"
                    value={newDNAT.internal_ip}
                    onChange={(e) => setNewDNAT({ ...newDNAT, internal_ip: e.target.value })}
                    placeholder="192.168.1.100"
                  />
                  <p className="text-xs text-muted-foreground">IP do servidor privado</p>
                </div>

                <div className="w-24 space-y-2">
                  <Label htmlFor="internal-port">Porta *</Label>
                  <Input
                    id="internal-port"
                    type="number"
                    min={1}
                    max={65535}
                    value={newDNAT.internal_port}
                    onChange={(e) => setNewDNAT({ ...newDNAT, internal_port: e.target.value })}
                    placeholder="80"
                  />
                </div>
              </div>
            </div>

            <div className="p-3 bg-primary/10 border border-primary/20 rounded-lg">
              <p className="text-sm text-primary">
                <strong>Exemplo:</strong> Para expor um servidor web interno em 192.168.1.100:80
                na porta externa 8080, defina Porta Externa = 8080, IP Interno = 192.168.1.100, Porta = 80.
              </p>
            </div>

            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsDNATModalOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={createDNATMutation.isPending}>
                {createDNATMutation.isPending ? 'Criando...' : 'Criar Regra de Encaminhamento'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit DNAT Modal */}
      <Dialog open={isEditDNATModalOpen} onOpenChange={setIsEditDNATModalOpen}>
        <DialogContent onClose={() => setIsEditDNATModalOpen(false)} className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Editar Regra de Encaminhamento de Porta</DialogTitle>
            <DialogDescription>
              Modifique a configuração de encaminhamento de porta.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleEditDNAT} className="space-y-4 mt-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="edit-dnat-name">Nome da Regra *</Label>
                <Input
                  id="edit-dnat-name"
                  value={editDNATForm.name}
                  onChange={(e) => setEditDNATForm({ ...editDNATForm, name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-dnat-protocol">Protocolo</Label>
                <Select
                  id="edit-dnat-protocol"
                  value={editDNATForm.protocol}
                  onChange={(e) => setEditDNATForm({ ...editDNATForm, protocol: e.target.value })}
                  options={DNAT_PROTOCOL_OPTIONS}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-dnat-description">Descrição</Label>
              <Input
                id="edit-dnat-description"
                value={editDNATForm.description}
                onChange={(e) => setEditDNATForm({ ...editDNATForm, description: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-dnat-source">IPs de Origem Permitidos</Label>
              <Input
                id="edit-dnat-source"
                value={editDNATForm.source_network}
                onChange={(e) => setEditDNATForm({ ...editDNATForm, source_network: e.target.value })}
                placeholder="* (qualquer)"
              />
              <p className="text-xs text-muted-foreground">
                Use <code className="px-1 bg-muted rounded">*</code> para qualquer origem, ou especifique IP/CIDR
              </p>
            </div>

            <div className="p-4 bg-muted/50 rounded-lg space-y-4">
              <div className="flex items-center gap-4">
                <div className="flex-1 space-y-2">
                  <Label htmlFor="edit-external-port">Porta Externa *</Label>
                  <Input
                    id="edit-external-port"
                    type="number"
                    min={1}
                    max={65535}
                    value={editDNATForm.external_port}
                    onChange={(e) => setEditDNATForm({ ...editDNATForm, external_port: e.target.value })}
                  />
                </div>
                <ArrowRight className="h-6 w-6 text-muted-foreground mt-2" />
                <div className="flex-1 space-y-2">
                  <Label htmlFor="edit-internal-ip">IP Interno *</Label>
                  <Input
                    id="edit-internal-ip"
                    value={editDNATForm.internal_ip}
                    onChange={(e) => setEditDNATForm({ ...editDNATForm, internal_ip: e.target.value })}
                  />
                </div>
                <div className="w-24 space-y-2">
                  <Label htmlFor="edit-internal-port">Porta *</Label>
                  <Input
                    id="edit-internal-port"
                    type="number"
                    min={1}
                    max={65535}
                    value={editDNATForm.internal_port}
                    onChange={(e) => setEditDNATForm({ ...editDNATForm, internal_port: e.target.value })}
                  />
                </div>
              </div>
            </div>

            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setIsEditDNATModalOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={updateDNATMutation.isPending}>
                {updateDNATMutation.isPending ? 'Salvando...' : 'Salvar Alterações'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Reapply firewall rules confirmation */}
      <Dialog open={confirmReapply} onOpenChange={setConfirmReapply}>
        <DialogContent onClose={() => setConfirmReapply(false)}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><RefreshCw className="h-5 w-5 text-primary" /> Reaplicar regras</DialogTitle>
            <DialogDescription>
              Reescreve e reaplica todas as regras de firewall no sistema. As conexões existentes seguem ativas; use se as regras saíram de sincronia.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReapply(false)}>Cancelar</Button>
            <Button onClick={() => reapplyMutation.mutate()} disabled={reapplyMutation.isPending} className="gap-2">
              <RefreshCw className="h-4 w-4" />
              {reapplyMutation.isPending ? 'Reaplicando…' : 'Reaplicar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete NAT rule confirmation */}
      <Dialog open={!!natToDelete} onOpenChange={(open) => { if (!open) setNatToDelete(null) }}>
        <DialogContent onClose={() => setNatToDelete(null)}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Trash2 className="h-5 w-5 text-destructive" /> Excluir regra de encaminhamento
            </DialogTitle>
            <DialogDescription>
              {natToDelete ? (
                <>
                  Isso remove a regra <strong>{natToDelete.name}</strong> (porta{' '}
                  <span className="font-mono">{natToDelete.external_port}</span> →{' '}
                  <span className="font-mono">{natToDelete.internal_ip}:{natToDelete.internal_port}</span>) e a
                  regra de firewall associada. Esta ação não pode ser desfeita.
                </>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNatToDelete(null)}>Cancelar</Button>
            <Button
              variant="destructive"
              onClick={() => natToDelete && deleteNATMutation.mutate(natToDelete.id)}
              disabled={deleteNATMutation.isPending}
              className="gap-2"
            >
              <Trash2 className="h-4 w-4" />
              {deleteNATMutation.isPending ? 'Excluindo…' : 'Excluir'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
