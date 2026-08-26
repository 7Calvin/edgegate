import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { vpnApi } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { PageHeader } from '@/components/PageHeader'
import { formatBytes } from '@/lib/utils'
import { Download, RefreshCw, Shield, ShieldOff, Settings, Save, Plus, X, AlertTriangle, Pencil } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import type { VPNServerConfig } from '@/types'
import { getApiErrorMessage } from '@/lib/apiError'

export default function VPNPage() {
  const { user } = useAuthStore()
  const queryClient = useQueryClient()
  const { toast } = useToast()

  // Server config state
  const [configForm, setConfigForm] = useState<Partial<VPNServerConfig>>({})
  const [newDns, setNewDns] = useState('')
  const [newSplitDomain, setNewSplitDomain] = useState('')
  const [newRoute, setNewRoute] = useState('')

  // Server status
  const { data: serverStatus } = useQuery({
    queryKey: ['vpn-status'],
    queryFn: () => vpnApi.serverStatus().then((res) => res.data),
    enabled: user?.is_admin,
    refetchInterval: 30000,
  })

  // Server config (fetch when modal opens or when admin has profile)
  const { data: serverConfig, isLoading: configLoading } = useQuery({
    queryKey: ['vpn-server-config'],
    queryFn: () => vpnApi.getServerConfig().then((res) => res.data),
    enabled: user?.is_admin,
  })

  // Update form when config loads
  useEffect(() => {
    if (serverConfig) {
      setConfigForm(serverConfig)
    }
  }, [serverConfig])

  const updateConfigMutation = useMutation({
    mutationFn: (data: Partial<VPNServerConfig>) => vpnApi.updateServerConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vpn-server-config'] })
      toast({ title: 'Configuration saved', description: 'Some changes may require server restart' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Failed to save configuration' })
    },
  })

  // Sanitized payload for PUT /server/config (shared by Save and Download).
  const buildConfigPayload = (): Partial<VPNServerConfig> => {
    const dataToSave = { ...configForm }
    // Exclude network fields if not editable
    if (!serverConfig?.network_editable) {
      delete dataToSave.vpn_network
      delete dataToSave.vpn_netmask
    }
    // Remove metadata field that shouldn't be sent
    delete dataToSave.network_editable
    return dataToSave
  }

  const downloadServerConfigMutation = useMutation({
    // Persist any unsaved form edits first so the generated .ovpn reflects the
    // options currently shown in the UI (proto, DNS, routes, redirect-gateway…).
    // Without this, the download reads the last-saved config from disk and the
    // just-edited options don't come through.
    mutationFn: async () => {
      await vpnApi.updateServerConfig(buildConfigPayload())
      queryClient.invalidateQueries({ queryKey: ['vpn-server-config'] })
      return vpnApi.downloadServerConfig()
    },
    onSuccess: (response) => {
      const blob = new Blob([response.data], { type: 'application/x-openvpn-profile' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const serverHost = serverConfig?.server_host || 'vpn'
      const filename = serverHost.replace(/\./g, '-').replace(/:/g, '-')
      a.download = `${filename}.ovpn`
      a.click()
      window.URL.revokeObjectURL(url)
      toast({ title: 'Server config downloaded', description: 'Users authenticate with username and password' })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Failed to download server config' })
    },
  })

  const startServerMutation = useMutation({
    mutationFn: () => vpnApi.startServer(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vpn-status'] })
      toast({ title: 'Server started', description: 'OpenVPN server started successfully' })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Failed to start server', description: getApiErrorMessage(error) })
    },
  })

  const stopServerMutation = useMutation({
    mutationFn: () => vpnApi.stopServer(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vpn-status'] })
      toast({ title: 'Server stopped', description: 'OpenVPN server stopped successfully' })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Failed to stop server', description: getApiErrorMessage(error) })
    },
  })

  const restartServerMutation = useMutation({
    mutationFn: () => vpnApi.restartServer(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vpn-status'] })
      toast({ title: 'Server restarted', description: 'OpenVPN server restarted successfully' })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Failed to restart server', description: getApiErrorMessage(error) })
    },
  })

  const [confirmNetChange, setConfirmNetChange] = useState(false)
  const [netForm, setNetForm] = useState({ vpn_network: '', vpn_netmask: '' })
  const openNetModal = () => {
    setNetForm({ vpn_network: configForm.vpn_network || '', vpn_netmask: configForm.vpn_netmask || '' })
    setConfirmNetChange(true)
  }
  const changeNetMutation = useMutation({
    mutationFn: (data: { vpn_network: string; vpn_netmask: string }) => vpnApi.changeNetwork(data),
    onSuccess: (res: any) => {
      setConfirmNetChange(false)
      queryClient.invalidateQueries({ queryKey: ['vpn-server-config'] })
      queryClient.invalidateQueries({ queryKey: ['vpn-status'] })
      toast({ title: 'Rede da VPN alterada', description: res?.data?.message })
    },
    onError: (error: any) => {
      toast({ variant: 'destructive', title: 'Falha ao alterar a rede', description: error?.response?.data?.detail })
    },
  })

  const handleSaveConfig = () => {
    updateConfigMutation.mutate(buildConfigPayload())
  }

  const addDnsServer = () => {
    if (newDns && !configForm.dns_servers?.includes(newDns)) {
      setConfigForm({
        ...configForm,
        dns_servers: [...(configForm.dns_servers || []), newDns],
      })
      setNewDns('')
    }
  }

  const removeDnsServer = (dns: string) => {
    setConfigForm({
      ...configForm,
      dns_servers: configForm.dns_servers?.filter((d) => d !== dns) || [],
    })
  }

  const addSplitDomain = () => {
    const domain = newSplitDomain.trim().replace(/^\.+/, '')
    if (domain && !configForm.split_dns_domains?.includes(domain)) {
      setConfigForm({
        ...configForm,
        split_dns_domains: [...(configForm.split_dns_domains || []), domain],
      })
      setNewSplitDomain('')
    }
  }

  const removeSplitDomain = (domain: string) => {
    setConfigForm({
      ...configForm,
      split_dns_domains: configForm.split_dns_domains?.filter((d) => d !== domain) || [],
    })
  }

  const addRoute = () => {
    if (newRoute && !configForm.push_routes?.includes(newRoute)) {
      setConfigForm({
        ...configForm,
        push_routes: [...(configForm.push_routes || []), newRoute],
      })
      setNewRoute('')
    }
  }

  const removeRoute = (route: string) => {
    setConfigForm({
      ...configForm,
      push_routes: configForm.push_routes?.filter((r) => r !== route) || [],
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="OpenVPN"
        subtitle={user?.is_admin
          ? 'Configuração do servidor VPN e perfis de cliente'
          : 'Baixe seu perfil e conecte com usuário e senha'}
      />


      {/* Quick Start - Download .ovpn for non-admin users */}
      {!user?.is_admin && (
        <Card>
          <CardHeader className="p-4 pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Shield className="h-4 w-4" />
              Connect to VPN
            </CardTitle>
            <CardDescription className="text-xs">Download the VPN configuration file and connect using your credentials</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 p-4 pt-0">
            <div className="bg-muted p-4 rounded-lg">
              <h4 className="font-medium mb-2">How to connect:</h4>
              <ol className="list-decimal list-inside space-y-1 text-sm text-muted-foreground">
                <li>Contact your administrator to download the .ovpn configuration file</li>
                <li>Import the .ovpn file into your OpenVPN client</li>
                <li>Connect using your username: <code className="bg-background px-1 rounded">{user?.username}</code></li>
                <li>Enter your account password when prompted</li>
              </ol>
            </div>
            <p className="text-sm text-muted-foreground">
              Note: You don't need an individual VPN profile. Use your regular account credentials to connect.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Server Status (Admin) */}
      {user?.is_admin && serverStatus && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-border bg-card px-4 py-2 text-sm">
          <span className="text-muted-foreground">
            Status{' '}
            <span className={serverStatus.is_running ? 'text-success' : 'text-destructive'}>
              {serverStatus.is_running ? 'Running' : 'Stopped'}
            </span>
          </span>
          <span className="text-muted-foreground">
            Connected Clients <span className="text-foreground">{serverStatus.connected_clients}</span>
          </span>
          <span className="text-muted-foreground">
            Traffic In <span className="text-foreground">{formatBytes(serverStatus.total_bytes_in)}</span>
          </span>
          <span className="text-muted-foreground">
            Traffic Out <span className="text-foreground">{formatBytes(serverStatus.total_bytes_out)}</span>
          </span>
          <div className="ml-auto flex gap-2">
            {!serverStatus.is_running ? (
              <Button size="sm" onClick={() => startServerMutation.mutate()} disabled={startServerMutation.isPending}>
                {startServerMutation.isPending ? (
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Shield className="h-4 w-4 mr-2" />
                )}
                Start
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={() => stopServerMutation.mutate()} disabled={stopServerMutation.isPending}>
                {stopServerMutation.isPending ? (
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <ShieldOff className="h-4 w-4 mr-2" />
                )}
                Stop
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => restartServerMutation.mutate()} disabled={restartServerMutation.isPending || !serverStatus.is_running}>
              <RefreshCw className={`h-4 w-4 mr-2 ${restartServerMutation.isPending ? 'animate-spin' : ''}`} />
              Restart
            </Button>
          </div>
        </div>
      )}

      {/* Server Configuration (Admin) */}
      {user?.is_admin && (
        <Card>
          <CardHeader className="p-4 pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Settings className="h-4 w-4" />
                  Server Configuration
                </CardTitle>
                <CardDescription className="text-xs">OpenVPN server settings (changes may require restart)</CardDescription>
              </div>
              <Button
                size="sm"
                onClick={() => downloadServerConfigMutation.mutate()}
                disabled={downloadServerConfigMutation.isPending}
              >
                <Download className="h-4 w-4 mr-2" />
                Download .ovpn
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {configLoading ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
              </div>
            ) : (
              <div className="space-y-6">
                {/* Basic Settings */}
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="server_host">Server Host</Label>
                    <Input
                      id="server_host"
                      value={configForm.server_host || ''}
                      onChange={(e) => setConfigForm({ ...configForm, server_host: e.target.value })}
                      placeholder="vpn.domain.local"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="server_port">Port</Label>
                    <Input
                      id="server_port"
                      type="number"
                      value={configForm.server_port || 1194}
                      onChange={(e) => setConfigForm({ ...configForm, server_port: parseInt(e.target.value) })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="protocol">Protocol</Label>
                    <select
                      id="protocol"
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                      value={configForm.protocol || 'udp'}
                      onChange={(e) => setConfigForm({ ...configForm, protocol: e.target.value })}
                    >
                      <option value="udp">UDP</option>
                      <option value="tcp">TCP</option>
                    </select>
                  </div>
                </div>

                {/* Network Settings */}
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="vpn_network">VPN Network</Label>
                    <div className="relative">
                      <Input id="vpn_network" value={configForm.vpn_network || ''} readOnly className="bg-muted pr-10 font-mono" />
                      <button
                        type="button"
                        onClick={openNetModal}
                        title="Alterar rede da VPN"
                        className="absolute right-0 top-0 flex h-full items-center px-3 text-muted-foreground transition-colors hover:text-warning"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="vpn_netmask">Netmask</Label>
                    <Input id="vpn_netmask" value={configForm.vpn_netmask || ''} readOnly className="bg-muted font-mono" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="max_clients">Max Clients</Label>
                    <Input
                      id="max_clients"
                      type="number"
                      value={configForm.max_clients || 100}
                      onChange={(e) => setConfigForm({ ...configForm, max_clients: parseInt(e.target.value) })}
                    />
                  </div>
                </div>

                {/* Redirect Gateway Toggle */}
                <div className="flex items-center justify-between p-4 bg-secondary/50 rounded-lg">
                  <div>
                    <Label className="text-base font-medium">Redirect Gateway</Label>
                    <p className="text-sm text-muted-foreground">
                      Force all client traffic through VPN tunnel (full tunnel mode)
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setConfigForm({ ...configForm, redirect_gateway: !configForm.redirect_gateway })}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      configForm.redirect_gateway ? 'bg-primary' : 'bg-muted'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        configForm.redirect_gateway ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                {/* DNS Servers */}
                <div className="space-y-3">
                  <Label>DNS Servers</Label>
                  <p className="text-sm text-muted-foreground">
                    Resolvers empurrados aos clientes — funcionam com o Redirect Gateway ligado
                    <strong> ou</strong> desligado. Para nomes internos, coloque aqui o IP privado do
                    seu DNS (ex.: o AD); em split-tunnel uma rota-host até ele é adicionada
                    automaticamente. Lembre de incluir a subrede interna em <strong>Push Routes</strong>.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {configForm.dns_servers?.map((dns) => (
                      <span
                        key={dns}
                        className="inline-flex items-center gap-1 px-2 py-1 bg-secondary rounded-md text-sm"
                      >
                        {dns}
                        <button
                          type="button"
                          onClick={() => removeDnsServer(dns)}
                          className="text-muted-foreground hover:text-destructive"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      placeholder="8.8.8.8"
                      value={newDns}
                      onChange={(e) => setNewDns(e.target.value)}
                      className="max-w-xs"
                    />
                    <Button type="button" variant="outline" size="sm" onClick={addDnsServer}>
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                {/* DNS search domain(s) pushed to clients */}
                <div className="space-y-3 p-4 border border-border rounded-lg">
                  <div>
                    <Label className="text-base font-medium">Domínio de busca (DNS)</Label>
                    <p className="text-sm text-muted-foreground">
                      Sufixo DNS empurrado aos clientes (ex.: <span className="font-mono">host</span>{' '}
                      → <span className="font-mono">host.domain.local</span>). Coloque seus resolvers
                      (ex.: o DNS do AD) em <strong>DNS Servers</strong> acima — o AD resolve os nomes
                      internos e encaminha o resto.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label>Domínios</Label>
                    <div className="flex flex-wrap gap-2">
                      {configForm.split_dns_domains?.map((domain) => (
                        <span
                          key={domain}
                          className="inline-flex items-center gap-1 px-2 py-1 bg-secondary rounded-md text-sm font-mono"
                        >
                          {domain}
                          <button
                            type="button"
                            onClick={() => removeSplitDomain(domain)}
                            className="text-muted-foreground hover:text-destructive"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Input
                        placeholder="domain.local"
                        value={newSplitDomain}
                        onChange={(e) => setNewSplitDomain(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            addSplitDomain()
                          }
                        }}
                        className="max-w-xs"
                      />
                      <Button type="button" variant="outline" size="sm" onClick={addSplitDomain}>
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Push Routes */}
                <div className="space-y-3">
                  <Label>Push Routes (CIDR)</Label>
                  <div className="flex flex-wrap gap-2">
                    {configForm.push_routes?.map((route) => (
                      <span
                        key={route}
                        className="inline-flex items-center gap-1 px-2 py-1 bg-secondary rounded-md text-sm font-mono"
                      >
                        {route}
                        <button
                          type="button"
                          onClick={() => removeRoute(route)}
                          className="text-muted-foreground hover:text-destructive"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    {(!configForm.push_routes || configForm.push_routes.length === 0) && (
                      <span className="text-sm text-muted-foreground">No routes configured</span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      placeholder="192.168.1.0/24"
                      value={newRoute}
                      onChange={(e) => setNewRoute(e.target.value)}
                      className="max-w-xs font-mono"
                    />
                    <Button type="button" variant="outline" size="sm" onClick={addRoute}>
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                {/* Save Button */}
                <div className="flex justify-end pt-4 border-t">
                  <Button onClick={handleSaveConfig} disabled={updateConfigMutation.isPending}>
                    <Save className="h-4 w-4 mr-2" />
                    Save Configuration
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* VPN network change — big warning */}
      <Dialog open={confirmNetChange} onOpenChange={setConfirmNetChange}>
        <DialogContent onClose={() => setConfirmNetChange(false)}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-warning"><AlertTriangle className="h-5 w-5" /> Alterar a rede da VPN</DialogTitle>
            <DialogDescription>
              Rede atual:{' '}
              <span className="font-mono text-foreground">{configForm.vpn_network}/{configForm.vpn_netmask}</span>. Defina a nova subrede abaixo.
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="net-new">VPN Network</Label>
              <Input id="net-new" value={netForm.vpn_network} onChange={(e) => setNetForm({ ...netForm, vpn_network: e.target.value })} className="font-mono" placeholder="10.9.0.0" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mask-new">Netmask</Label>
              <Input id="mask-new" value={netForm.vpn_netmask} onChange={(e) => setNetForm({ ...netForm, vpn_netmask: e.target.value })} className="font-mono" placeholder="255.255.255.0" />
            </div>
          </div>

          <div className="my-2 space-y-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
            <p className="font-medium text-warning">Operação disruptiva — leia antes:</p>
            <ul className="space-y-1.5 text-foreground">
              <li className="flex gap-2"><span className="text-warning">•</span> O OpenVPN <span className="font-medium">reinicia</span> e todas as sessões ativas caem.</li>
              <li className="flex gap-2"><span className="text-warning">•</span> O <span className="font-medium">IP de VPN de todos os clientes muda</span> (reatribuído na nova subrede).</li>
              <li className="flex gap-2"><span className="text-warning">•</span> Regras de firewall/rotas que citam a subrede antiga podem precisar de revisão.</li>
              <li className="flex gap-2"><span className="text-success">•</span> Clientes <span className="font-medium">não</span> precisam baixar o .ovpn de novo — só reconectar.</li>
            </ul>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmNetChange(false)}>Cancelar</Button>
            <Button
              variant="destructive"
              onClick={() => changeNetMutation.mutate(netForm)}
              disabled={changeNetMutation.isPending || !netForm.vpn_network || !netForm.vpn_netmask}
              className="gap-2"
            >
              <AlertTriangle className="h-4 w-4" />
              {changeNetMutation.isPending ? 'Alterando…' : 'Alterar rede'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
