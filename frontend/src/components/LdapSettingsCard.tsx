import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi, type LdapSettings, type LdapSyncResult } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { Network, Save, PlugZap, Eye, EyeOff, CheckCircle2, XCircle, Users, RefreshCw } from 'lucide-react'

interface FormState {
  enabled: boolean
  server: string
  port: number
  use_ntlm: boolean
  ad_domain: string
  bind_dn: string
  bind_password: string
  search_base: string
  user_attr: string
  required_group_dn: string
  timeout: number
}

const emptyForm: FormState = {
  enabled: false,
  server: '',
  port: 389,
  use_ntlm: true,
  ad_domain: '',
  bind_dn: '',
  bind_password: '',
  search_base: '',
  user_attr: 'sAMAccountName',
  required_group_dn: '',
  timeout: 5,
}

export default function LdapSettingsCard() {
  const { toast } = useToast()
  const [form, setForm] = useState<FormState>(emptyForm)
  const [passwordSet, setPasswordSet] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string | null } | null>(null)

  const { data, refetch } = useQuery({
    queryKey: ['ldap-settings'],
    queryFn: () => adminApi.getLdapSettings().then((res) => res.data),
  })

  // Hydrate the form from the server (password is never returned — only a flag).
  useEffect(() => {
    if (!data) return
    const s: LdapSettings = data
    setForm({
      enabled: s.enabled,
      server: s.server ?? '',
      port: s.port ?? 389,
      use_ntlm: s.use_ntlm ?? true,
      ad_domain: s.ad_domain ?? '',
      bind_dn: s.bind_dn ?? '',
      bind_password: '',
      search_base: s.search_base ?? '',
      user_attr: s.user_attr ?? 'sAMAccountName',
      required_group_dn: s.required_group_dn ?? '',
      timeout: s.timeout ?? 5,
    })
    setPasswordSet(s.bind_password_set)
  }, [data])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const saveMutation = useMutation({
    mutationFn: () =>
      adminApi.updateLdapSettings({
        enabled: form.enabled,
        server: form.server || null,
        port: form.port,
        use_ntlm: form.use_ntlm,
        ad_domain: form.ad_domain || null,
        bind_dn: form.bind_dn || null,
        // Empty string keeps the stored password unchanged.
        bind_password: form.bind_password || undefined,
        search_base: form.search_base || null,
        user_attr: form.user_attr || 'sAMAccountName',
        required_group_dn: form.required_group_dn || null,
        timeout: form.timeout,
      }),
    onSuccess: () => {
      toast({ title: 'Configuração do AD salva' })
      setForm((f) => ({ ...f, bind_password: '' }))
      refetch()
    },
    onError: (error: any) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao salvar',
        description: error?.response?.data?.detail || error?.response?.data?.message,
      })
    },
  })

  const testMutation = useMutation({
    mutationFn: () =>
      adminApi.testLdapSettings({
        server: form.server || null,
        port: form.port,
        use_ntlm: form.use_ntlm,
        ad_domain: form.ad_domain || null,
        bind_dn: form.bind_dn || null,
        bind_password: form.bind_password || undefined,
        search_base: form.search_base || null,
        timeout: form.timeout,
      }),
    onSuccess: (res) => {
      setTestResult({ ok: res.data.success, message: res.data.message })
    },
    onError: (error: any) => {
      setTestResult({
        ok: false,
        message: error?.response?.data?.detail || 'Erro ao testar conexão',
      })
    },
  })

  const queryClient = useQueryClient()
  const [deleteMode, setDeleteMode] = useState<'deactivate' | 'delete' | 'keep'>('deactivate')
  const [syncPreview, setSyncPreview] = useState<LdapSyncResult | null>(null)
  const [syncResult, setSyncResult] = useState<LdapSyncResult | null>(null)

  const previewMutation = useMutation({
    mutationFn: (mode: string) => adminApi.syncLdapGroup({ delete_mode: mode, dry_run: true }),
    onSuccess: (res) => { setSyncResult(null); setSyncPreview(res.data) },
    onError: (error: any) => {
      setSyncPreview(null)
      toast({
        variant: 'destructive',
        title: 'Falha ao pré-visualizar',
        description: error?.response?.data?.detail || error?.response?.data?.message,
      })
    },
  })

  const syncMutation = useMutation({
    mutationFn: (mode: string) => adminApi.syncLdapGroup({ delete_mode: mode, dry_run: false }),
    onSuccess: (res) => {
      setSyncPreview(null)
      setSyncResult(res.data)
      toast({ title: 'Sincronização concluída', description: res.data.message || undefined })
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error: any) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao sincronizar',
        description: error?.response?.data?.detail || error?.response?.data?.message,
      })
    },
  })

  const modeLabel = (n: number) =>
    deleteMode === 'delete' ? `${n} remover` : deleteMode === 'keep' ? `${n} manter` : `${n} desativar`

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Network className="h-5 w-5" />
          Autenticação Active Directory (LDAP)
        </CardTitle>
        <CardDescription>
          Autentica usuários da VPN contra o AD, liberando acesso por grupo. Contas locais
          continuam funcionando em paralelo. Desligado = apenas base local.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Enable toggle */}
        <div className="flex items-center justify-between gap-4 rounded-lg border border-border p-3">
          <div>
            <p className="font-medium">Habilitar autenticação AD</p>
            <p className="text-sm text-muted-foreground">
              Usuários do grupo da VPN no AD poderão conectar.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={form.enabled}
            onClick={() => set('enabled', !form.enabled)}
            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0 transition-colors ${
              form.enabled ? 'bg-primary' : 'bg-secondary'
            }`}
          >
            <span
              className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                form.enabled ? 'translate-x-[22px]' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ldap-server">Servidor (Domain Controller)</Label>
            <Input
              id="ldap-server"
              value={form.server}
              onChange={(e) => set('server', e.target.value)}
              placeholder="10.0.0.10 ou dc.domain.local"
              className="font-mono"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ldap-port">Porta</Label>
            <Input
              id="ldap-port"
              type="number"
              value={form.port}
              onChange={(e) => set('port', parseInt(e.target.value || '389', 10))}
              className="font-mono"
            />
          </div>
        </div>

        {/* NTLM signed bind toggle */}
        <div className="flex items-center justify-between gap-4 rounded-lg border border-border p-3">
          <div>
            <p className="font-medium">Bind NTLM assinado (recomendado p/ AD)</p>
            <p className="text-sm text-muted-foreground">
              ADs modernos recusam bind simples em texto claro na 389. O NTLM assina a
              sessão e conecta na mesma 389, sem LDAPS e sem mexer no AD. O domínio é
              detectado automaticamente pela base de busca.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={form.use_ntlm}
            onClick={() => set('use_ntlm', !form.use_ntlm)}
            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0 transition-colors ${
              form.use_ntlm ? 'bg-primary' : 'bg-secondary'
            }`}
          >
            <span
              className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                form.use_ntlm ? 'translate-x-[22px]' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        <div className="space-y-2">
          <Label htmlFor="ldap-bind-dn">
            {form.use_ntlm ? 'Conta de serviço (usuário)' : 'Bind DN (conta de serviço)'}
          </Label>
          <Input
            id="ldap-bind-dn"
            value={form.bind_dn}
            onChange={(e) => set('bind_dn', e.target.value)}
            placeholder={form.use_ntlm ? 'seven  (ou DOMAIN\\seven)' : 'CN=svc-vpn,OU=Service,DC=domain,DC=local'}
            className="font-mono"
          />
          {form.use_ntlm && (
            <p className="text-xs text-muted-foreground">
              No modo NTLM use o nome da conta (sAMAccountName) ou DOMÍNIO\usuário — não o DN completo.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="ldap-bind-pass">Senha do bind</Label>
          <div className="relative">
            <Input
              id="ldap-bind-pass"
              type={showPassword ? 'text' : 'password'}
              value={form.bind_password}
              onChange={(e) => set('bind_password', e.target.value)}
              placeholder={passwordSet ? '•••••••• (mantida)' : 'senha da conta de serviço'}
              className="pr-10 font-mono"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4 text-muted-foreground" />
              ) : (
                <Eye className="h-4 w-4 text-muted-foreground" />
              )}
            </Button>
          </div>
          {passwordSet && (
            <p className="text-xs text-muted-foreground">
              Deixe em branco para manter a senha atual.
            </p>
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ldap-base">Base de busca</Label>
            <Input
              id="ldap-base"
              value={form.search_base}
              onChange={(e) => set('search_base', e.target.value)}
              placeholder="DC=domain,DC=local"
              className="font-mono"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ldap-user-attr">Atributo de login</Label>
            <Input
              id="ldap-user-attr"
              value={form.user_attr}
              onChange={(e) => set('user_attr', e.target.value)}
              placeholder="sAMAccountName"
              className="font-mono"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="ldap-group">Grupo da VPN (DN)</Label>
          <Input
            id="ldap-group"
            value={form.required_group_dn}
            onChange={(e) => set('required_group_dn', e.target.value)}
            placeholder="CN=VPN-Users,OU=Groups,DC=domain,DC=local"
            className="font-mono"
          />
          <p className="text-xs text-muted-foreground">
            Só usuários deste grupo conectam. Grupos aninhados (grupo dentro de grupo) são
            resolvidos automaticamente.
          </p>
        </div>

        {/* Group user sync */}
        <div className="space-y-3 rounded-lg border border-border p-3">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-muted-foreground" />
            <p className="font-medium">Sincronizar usuários do grupo</p>
          </div>
          <p className="text-sm text-muted-foreground">
            Importa como usuários locais todos os membros do grupo da VPN no AD, sem esperar
            o primeiro login. Contas que saíram do grupo seguem a ação escolhida abaixo.
          </p>
          <p className="flex items-start gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Sincronização automática ativa: o grupo é sincronizado sozinho{' '}
              <span className="font-medium text-foreground">a cada 1 hora</span> (quem sai do grupo
              é desativado, de forma reversível). O botão abaixo continua disponível para
              sincronizar na hora.
            </span>
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="ldap-sync-mode">Quem saiu do grupo</Label>
              <select
                id="ldap-sync-mode"
                value={deleteMode}
                onChange={(e) => {
                  const v = e.target.value as 'deactivate' | 'delete' | 'keep'
                  setDeleteMode(v)
                  if (syncPreview) previewMutation.mutate(v)
                }}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="deactivate">Desativar (reversível)</option>
                <option value="delete">Excluir (apaga)</option>
                <option value="keep">Manter na lista</option>
              </select>
            </div>
            <Button
              variant="outline"
              onClick={() => previewMutation.mutate(deleteMode)}
              disabled={previewMutation.isPending || !form.required_group_dn || !form.enabled}
            >
              <Users className="mr-2 h-4 w-4" />
              {previewMutation.isPending ? 'Analisando...' : 'Sincronizar grupo'}
            </Button>
          </div>

          {syncPreview && (
            <div className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
              <p className="font-medium">Prévia — {syncPreview.total_in_group} no grupo</p>
              <p className="text-muted-foreground">
                +{syncPreview.added} adicionar · {modeLabel(syncPreview.removed)} · {syncPreview.reactivated} reativar · {syncPreview.skipped} preservar
              </p>
              {deleteMode === 'delete' && syncPreview.removed > 0 && (
                <p className="text-destructive">
                  Atenção: {syncPreview.removed} usuário(s) serão APAGADOS permanentemente (perfil e histórico).
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setSyncPreview(null)}>
                  Cancelar
                </Button>
                <Button size="sm" onClick={() => syncMutation.mutate(deleteMode)} disabled={syncMutation.isPending}>
                  <RefreshCw className={`mr-2 h-4 w-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
                  {syncMutation.isPending ? 'Sincronizando...' : 'Confirmar'}
                </Button>
              </div>
            </div>
          )}

          {syncResult && (
            <div className="flex items-start gap-2 rounded-md border border-success/40 bg-success/10 p-3 text-sm text-success">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{syncResult.message}</span>
            </div>
          )}
        </div>

        {/* Test result */}
        {testResult && (
          <div
            className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${
              testResult.ok
                ? 'border-success/40 bg-success/10 text-success'
                : 'border-destructive/40 bg-destructive/10 text-destructive'
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            ) : (
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            )}
            <span>{testResult.ok ? 'Conexão bem-sucedida.' : testResult.message}</span>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          <Button
            variant="outline"
            onClick={() => { setTestResult(null); testMutation.mutate() }}
            disabled={testMutation.isPending || !form.server}
          >
            <PlugZap className="mr-2 h-4 w-4" />
            {testMutation.isPending ? 'Testando...' : 'Testar conexão'}
          </Button>
          <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            <Save className="mr-2 h-4 w-4" />
            {saveMutation.isPending ? 'Salvando...' : 'Salvar'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
