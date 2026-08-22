import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/auth'
import { authApi, proxyApi } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { PageHeader } from '@/components/PageHeader'
import { TIMEZONES, getTimezone, setTimezone } from '@/lib/tz'
import { Shield, Key, User, Lock, Copy, Check, Eye, EyeOff, Server, Pencil, RefreshCw, Save, ScrollText, Clock, Network, AlertTriangle } from 'lucide-react'
import SystemUpdateCard from '@/components/SystemUpdateCard'
import LdapSettingsCard from '@/components/LdapSettingsCard'
import { Link, useSearchParams } from 'react-router-dom'

export default function SettingsPage() {
  const { user, checkAuth } = useAuthStore()
  const { toast } = useToast()
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<'conta' | 'auth' | 'sistema'>('conta')
  // Deep-link support: /settings?tab=auth opens the AD tab (e.g. from the
  // command palette). Admin-only tabs fall back to "conta" for non-admins.
  useEffect(() => {
    const t = searchParams.get('tab')
    if ((t === 'auth' || t === 'sistema') && user?.is_admin) setTab(t)
    else if (t === 'conta') setTab('conta')
  }, [searchParams, user?.is_admin])
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [mfaCode, setMfaCode] = useState('')
  const [disableMfaCode, setDisableMfaCode] = useState('')
  const [qrCode, setQrCode] = useState<string | null>(null)
  const [backupCodes, setBackupCodes] = useState<string[]>([])
  const [copiedCodes, setCopiedCodes] = useState(false)
  const [editDomain, setEditDomain] = useState('')
  const [isEditingDomain, setIsEditingDomain] = useState(false)
  const [showMfa, setShowMfa] = useState(false)
  const [showPasswordForm, setShowPasswordForm] = useState(false)
  // Log/audit config (preview — UI only for now)
  const [tz, setTz] = useState(getTimezone())
  const [logRetention, setLogRetention] = useState('90')
  const [logMinSev, setLogMinSev] = useState('info')
  const [logCats, setLogCats] = useState<Record<string, boolean>>({ auth: true, vpn: true, config: true, system: true, users: true })

  // Management panel domain (admin only)
  const { data: mgmtDomain, refetch: refetchMgmtDomain } = useQuery({
    queryKey: ['management-domain'],
    queryFn: () => proxyApi.getManagementDomain().then((res) => res.data),
    enabled: user?.is_admin,
  })

  const updateDomainMutation = useMutation({
    mutationFn: (domain: string) => proxyApi.updateManagementDomain({ domain }),
    onSuccess: (res: any) => {
      refetchMgmtDomain()
      toast({ title: res?.data?.message || 'Domain updated' })
      setIsEditingDomain(false)
    },
    onError: (error: any) => {
      toast({
        variant: 'destructive',
        title: 'Failed to update domain',
        description: error?.response?.data?.detail || error?.response?.data?.message,
      })
    },
  })

  // Certificate status for the management domain
  const { data: certInfo, refetch: refetchCert } = useQuery({
    queryKey: ['management-cert', mgmtDomain?.domain],
    queryFn: () => proxyApi.certificateDetails(mgmtDomain.domain).then((res: any) => res.data).catch(() => null),
    enabled: !!(user?.is_admin && mgmtDomain?.domain),
  })

  const renewCertMutation = useMutation({
    mutationFn: (domain: string) => proxyApi.renewCertificate(domain),
    onSuccess: (res: any) => {
      toast({
        title: res?.data?.message || 'Certificate renewal triggered',
        description: 'Traefik is re-issuing — it can take up to a minute.',
      })
      setTimeout(() => refetchCert(), 30000)
    },
    onError: (error: any) => {
      toast({
        variant: 'destructive',
        title: 'Failed to regenerate certificate',
        description: error?.response?.data?.detail || error?.response?.data?.message,
      })
    },
  })

  const [armReissue, setArmReissue] = useState(false)
  const reissueCertMutation = useMutation({
    mutationFn: (domain: string) => proxyApi.reissueCertificate(domain),
    onSuccess: (res: any) => {
      toast({
        title: res?.data?.message || 'Reemitindo certificado',
        description: 'O proxy está reiniciando — aguarde ~1 min e recarregue a página.',
      })
      setArmReissue(false)
      setTimeout(() => refetchCert(), 45000)
    },
    onError: (error: any) => {
      toast({
        variant: 'destructive',
        title: 'Falha ao forçar reemissão',
        description: error?.response?.data?.detail || error?.response?.data?.message,
      })
    },
  })

  const changePasswordMutation = useMutation({
    mutationFn: () => authApi.changePassword(currentPassword, newPassword, confirmPassword),
    onSuccess: () => {
      toast({ title: 'Password changed successfully' })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    },
    onError: (error: any) => {
      const message = error.response?.data?.message || 'Failed to change password'
      toast({ variant: 'destructive', title: message })
    },
  })

  const setupMfaMutation = useMutation({
    mutationFn: () => authApi.setupMfa(),
    onSuccess: (response) => {
      const { qr_code, backup_codes } = response.data
      setQrCode(qr_code)
      setBackupCodes(backup_codes || [])
      toast({
        title: 'MFA Setup',
        description: 'Scan the QR code with your authenticator app',
      })
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Failed to setup MFA' })
    },
  })

  const verifyMfaMutation = useMutation({
    mutationFn: () => authApi.verifyMfa(mfaCode),
    onSuccess: () => {
      toast({ title: 'MFA enabled successfully' })
      setMfaCode('')
      setQrCode(null)
      setBackupCodes([])
      checkAuth()
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Invalid MFA code' })
    },
  })

  const disableMfaMutation = useMutation({
    mutationFn: () => authApi.disableMfa(currentPassword, disableMfaCode),
    onSuccess: () => {
      toast({ title: 'MFA disabled' })
      setCurrentPassword('')
      setDisableMfaCode('')
      checkAuth()
    },
    onError: (error: any) => {
      const message = error.response?.data?.message || 'Failed to disable MFA'
      toast({ variant: 'destructive', title: message })
    },
  })

  const handleChangePassword = () => {
    if (newPassword !== confirmPassword) {
      toast({ variant: 'destructive', title: 'Passwords do not match' })
      return
    }
    if (newPassword.length < 12) {
      toast({ variant: 'destructive', title: 'Password must be at least 12 characters' })
      return
    }
    changePasswordMutation.mutate()
  }

  const tabs = [
    { id: 'conta' as const, label: 'Conta', icon: User, show: true },
    { id: 'auth' as const, label: 'Autenticação AD', icon: Network, show: !!user?.is_admin },
    { id: 'sistema' as const, label: 'Sistema', icon: Server, show: !!user?.is_admin },
  ].filter((t) => t.show)

  return (
    <div className="space-y-6">
      <PageHeader title="Configurações" subtitle="Gerencie sua conta e o sistema" />

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-border">
        {tabs.map((t) => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`-mb-px inline-flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon className="h-4 w-4" /> {t.label}
            </button>
          )
        })}
      </div>

      <div className="max-w-3xl space-y-6">
      {/* Conta — Perfil */}
      {tab === 'conta' && (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-5 w-5" />
            Informações do perfil
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm text-muted-foreground">Usuário</p>
            <p className="font-medium text-foreground">{user?.username}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Email</p>
            <p className="font-medium text-foreground">{user?.email}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Tipo de conta</p>
            <p className="font-medium text-foreground">{user?.is_admin ? 'Admin' : 'Usuário'}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Papel</p>
            <p className="font-medium text-foreground">{user?.is_admin ? 'Administrador' : 'Usuário'}</p>
          </div>
        </CardContent>
      </Card>
      )}

      {/* Conta — Segurança */}
      {tab === 'conta' && (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Segurança
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="divide-y divide-border">
            {/* Row A — Two-Factor Authentication */}
            <div className="flex items-center justify-between gap-4 py-4 first:pt-0">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center">
                  <Shield className="h-5 w-5" />
                </div>
                <div>
                  <p className="font-medium">Autenticação de dois fatores</p>
                  <p className="text-sm text-muted-foreground">
                    {user?.mfa_enabled
                      ? 'Ativado'
                      : user?.mfa_required
                      ? 'MFA obrigatório para a sua conta'
                      : 'Adicione uma camada extra de segurança'}
                  </p>
                </div>
              </div>
              {user?.mfa_enabled ? (
                <Button variant="outline" onClick={() => setShowMfa(!showMfa)}>
                  Gerenciar
                </Button>
              ) : (
                <Button onClick={() => setShowMfa(!showMfa)}>
                  Configurar MFA
                </Button>
              )}
            </div>

            {/* Row B — Password */}
            <div className="flex items-center justify-between gap-4 py-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center">
                  <Lock className="h-5 w-5" />
                </div>
                <div>
                  <p className="font-medium">Senha</p>
                  <p className="text-sm text-muted-foreground">Altere sua senha periodicamente</p>
                </div>
              </div>
              <Button variant="outline" onClick={() => setShowPasswordForm(!showPasswordForm)}>
                Alterar senha
              </Button>
            </div>
          </div>

          {/* MFA form (toggle) */}
          {showMfa && (
            <div className="mt-6 border-t border-border pt-6 space-y-4">
              {user?.mfa_enabled ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-success">
                    <Shield className="h-5 w-5" />
                    <span>MFA está ativado</span>
                  </div>
                  {user?.mfa_required && (
                    <p className="text-sm text-warning">
                      O MFA é obrigatório para a sua conta e não pode ser desativado.
                    </p>
                  )}
                  {!user?.mfa_required && (
                    <>
                      <div className="space-y-2">
                        <Label htmlFor="disable-password">Senha</Label>
                        <div className="relative">
                          <Input
                            id="disable-password"
                            type={showCurrentPassword ? 'text' : 'password'}
                            value={currentPassword}
                            onChange={(e) => setCurrentPassword(e.target.value)}
                            className="pr-10"
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                            onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                          >
                            {showCurrentPassword ? (
                              <EyeOff className="h-4 w-4 text-muted-foreground" />
                            ) : (
                              <Eye className="h-4 w-4 text-muted-foreground" />
                            )}
                          </Button>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="disable-mfa-code">Código MFA</Label>
                        <Input
                          id="disable-mfa-code"
                          type="text"
                          maxLength={6}
                          value={disableMfaCode}
                          onChange={(e) => setDisableMfaCode(e.target.value.replace(/\D/g, ''))}
                          placeholder="000000"
                          className="w-32 font-mono"
                        />
                      </div>
                      <Button
                        variant="destructive"
                        onClick={() => disableMfaMutation.mutate()}
                        disabled={disableMfaMutation.isPending || !currentPassword || disableMfaCode.length !== 6}
                      >
                        Desativar MFA
                      </Button>
                    </>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {!qrCode ? (
                    <Button onClick={() => setupMfaMutation.mutate()} disabled={setupMfaMutation.isPending}>
                      <Key className="h-4 w-4 mr-2" />
                      Configurar MFA
                    </Button>
                  ) : (
                    <div className="space-y-6">
                      {/* QR Code Section */}
                      <div className="space-y-3">
                        <Label className="text-base font-semibold">1. Escaneie o QR Code</Label>
                        <p className="text-sm text-muted-foreground">
                          Escaneie este QR code com seu aplicativo autenticador (Google Authenticator, Authy, etc.)
                        </p>
                        <div className="flex justify-center p-4 bg-white rounded-lg">
                          <img
                            src={qrCode}
                            alt="MFA QR Code"
                            className="w-48 h-48"
                          />
                        </div>
                      </div>

                      {/* Backup Codes Section */}
                      {backupCodes.length > 0 && (
                        <div className="space-y-3">
                          <Label className="text-base font-semibold">2. Salve os códigos de backup</Label>
                          <p className="text-sm text-muted-foreground">
                            Guarde estes códigos de backup em um lugar seguro. Cada código só pode ser usado uma vez.
                          </p>
                          <div className="bg-muted p-4 rounded-lg font-mono text-sm">
                            <div className="grid grid-cols-2 gap-2">
                              {backupCodes.map((code, i) => (
                                <span key={i} className="text-center">{code}</span>
                              ))}
                            </div>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              navigator.clipboard.writeText(backupCodes.join('\n'))
                              setCopiedCodes(true)
                              setTimeout(() => setCopiedCodes(false), 2000)
                            }}
                          >
                            {copiedCodes ? (
                              <>
                                <Check className="h-4 w-4 mr-2" />
                                Copiado!
                              </>
                            ) : (
                              <>
                                <Copy className="h-4 w-4 mr-2" />
                                Copiar códigos
                              </>
                            )}
                          </Button>
                        </div>
                      )}

                      {/* Verification Section */}
                      <div className="space-y-3">
                        <Label className="text-base font-semibold">3. Verifique a configuração</Label>
                        <p className="text-sm text-muted-foreground">
                          Digite o código de 6 dígitos do seu aplicativo autenticador para verificar a configuração.
                        </p>
                        <div className="flex gap-2">
                          <Input
                            id="mfa-code"
                            type="text"
                            maxLength={6}
                            value={mfaCode}
                            onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                            placeholder="000000"
                            className="w-32 text-center font-mono text-lg"
                          />
                          <Button
                            onClick={() => verifyMfaMutation.mutate()}
                            disabled={verifyMfaMutation.isPending || mfaCode.length !== 6}
                          >
                            Verificar e ativar
                          </Button>
                        </div>
                      </div>

                      {/* Cancel Button */}
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setQrCode(null)
                          setBackupCodes([])
                          setMfaCode('')
                        }}
                      >
                        Cancelar configuração
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Password form (toggle) */}
          {showPasswordForm && (
            <div className="mt-6 border-t border-border pt-6 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="current-password">Senha atual</Label>
                <div className="relative">
                  <Input
                    id="current-password"
                    type={showCurrentPassword ? 'text' : 'password'}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    className="pr-10"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                    onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                  >
                    {showCurrentPassword ? (
                      <EyeOff className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <Eye className="h-4 w-4 text-muted-foreground" />
                    )}
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="new-password">Nova senha</Label>
                <div className="relative">
                  <Input
                    id="new-password"
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="pr-10"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                  >
                    {showNewPassword ? (
                      <EyeOff className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <Eye className="h-4 w-4 text-muted-foreground" />
                    )}
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirmar nova senha</Label>
                <div className="relative">
                  <Input
                    id="confirm-password"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="pr-10"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <Eye className="h-4 w-4 text-muted-foreground" />
                    )}
                  </Button>
                </div>
              </div>
              <Button
                onClick={handleChangePassword}
                disabled={changePasswordMutation.isPending || !currentPassword || !newPassword}
              >
                Alterar senha
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {/* Sistema — Management Panel Domain */}
      {user?.is_admin && tab === 'sistema' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-5 w-5" />
              Management Panel Domain
            </CardTitle>
            <CardDescription>
              Domain used to access this management panel
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!mgmtDomain ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : isEditingDomain ? (
              <div className="flex items-center gap-3">
                <Input
                  value={editDomain}
                  onChange={(e) => setEditDomain(e.target.value)}
                  placeholder="vpn.domain.local"
                  className="max-w-sm font-mono"
                />
                <Button
                  size="sm"
                  onClick={() => {
                    if (editDomain.trim()) {
                      updateDomainMutation.mutate(editDomain.trim())
                    }
                  }}
                  disabled={updateDomainMutation.isPending || !editDomain.trim()}
                >
                  <Save className="h-4 w-4 mr-1" />
                  {updateDomainMutation.isPending ? 'Saving...' : 'Save'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setIsEditingDomain(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-4 md:grid-cols-3">
                  <div>
                    <p className="text-sm text-muted-foreground">Domain</p>
                    <p className="font-mono font-medium">
                      {mgmtDomain.domain || <span className="text-muted-foreground">Not configured</span>}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Certificate</p>
                    {certInfo ? (
                      <p className={
                        certInfo.status === 'valid' ? 'text-success font-medium'
                          : certInfo.status === 'expiring' ? 'text-warning font-medium'
                          : 'text-destructive font-medium'
                      }>
                        {certInfo.status === 'valid' ? 'Valid'
                          : certInfo.status === 'expiring' ? 'Expiring'
                          : certInfo.status === 'expired' ? 'Expired' : 'Error'}
                        {typeof certInfo.days_remaining === 'number' ? ` · ${certInfo.days_remaining}d left` : ''}
                      </p>
                    ) : (
                      <p className="text-muted-foreground">Not issued (self-signed)</p>
                    )}
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">SSL</p>
                    <p className={mgmtDomain.ssl_enabled ? 'text-success font-medium' : 'text-muted-foreground'}>
                      {mgmtDomain.ssl_enabled ? 'Let\'s Encrypt' : 'Disabled'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setEditDomain(mgmtDomain.domain || '')
                      setIsEditingDomain(true)
                    }}
                  >
                    <Pencil className="h-4 w-4 mr-1" />
                    Change Domain
                  </Button>
                  {mgmtDomain.domain && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => renewCertMutation.mutate(mgmtDomain.domain)}
                      disabled={renewCertMutation.isPending}
                    >
                      <RefreshCw className="h-4 w-4 mr-1" />
                      {renewCertMutation.isPending ? 'Regenerating...' : 'Regenerate cert'}
                    </Button>
                  )}
                  {mgmtDomain.domain && !armReissue && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setArmReissue(true)}
                      title="Reinicia o proxy para reemitir o certificado — interrompe HTTPS por ~30s"
                    >
                      <AlertTriangle className="h-4 w-4 mr-1" />
                      Forçar reemissão
                    </Button>
                  )}
                  {armReissue && (
                    <>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => reissueCertMutation.mutate(mgmtDomain.domain)}
                        disabled={reissueCertMutation.isPending}
                      >
                        {reissueCertMutation.isPending ? 'Reiniciando…' : 'Confirmar — reinicia o proxy (~30s)'}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setArmReissue(false)}>
                        Cancelar
                      </Button>
                    </>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => { refetchMgmtDomain(); refetchCert() }}>
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Changing the domain updates the Traefik routing and restarts affected services — make sure DNS already points here (the panel stays reachable via its IP if not). "Regenerate cert" re-issues the Let's Encrypt certificate (needs port 80 reachable from the internet).
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Sistema — Logs & Auditoria */}
      {user?.is_admin && tab === 'sistema' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ScrollText className="h-5 w-5" /> Logs & Auditoria</CardTitle>
            <CardDescription>Retenção e o que registrar (prévia — ainda não persistido)</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label className="flex items-center gap-2"><Clock className="h-4 w-4" /> Fuso horário (exibição)</Label>
              <select
                value={tz}
                onChange={(e) => { setTz(e.target.value); setTimezone(e.target.value); toast({ title: 'Fuso horário atualizado', description: 'Aplicado aos horários do painel (recarregue as telas para ver em tudo).' }) }}
                className="h-9 w-full max-w-xs rounded-lg border border-border bg-secondary/40 px-3 text-sm text-foreground focus:border-primary/50 focus:outline-none"
              >
                {TIMEZONES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <p className="text-xs text-muted-foreground">Os horários são guardados em UTC e exibidos neste fuso.</p>
            </div>

            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-medium text-foreground">Registro de eventos</p>
                <p className="text-sm text-muted-foreground">Login, VPN, alterações de configuração, sistema…</p>
              </div>
              <Link to="/audit"><Button variant="outline" size="sm">Abrir Auditoria</Button></Link>
            </div>

            <div className="space-y-2">
              <Label>Retenção dos logs</Label>
              <select
                value={logRetention}
                onChange={(e) => setLogRetention(e.target.value)}
                className="h-9 w-full max-w-xs rounded-lg border border-border bg-secondary/40 px-3 text-sm text-foreground focus:border-primary/50 focus:outline-none"
              >
                <option value="30">30 dias</option>
                <option value="60">60 dias</option>
                <option value="90">90 dias</option>
                <option value="180">180 dias</option>
                <option value="365">1 ano</option>
              </select>
              <p className="text-xs text-muted-foreground">Eventos mais antigos que isso são removidos automaticamente.</p>
            </div>

            <div className="space-y-2">
              <Label>Categorias registradas</Label>
              <div className="flex flex-wrap gap-2">
                {([['auth', 'Autenticação'], ['vpn', 'OpenVPN'], ['config', 'Configuração'], ['system', 'Sistema'], ['users', 'Usuários']] as const).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setLogCats((c) => ({ ...c, [key]: !c[key] }))}
                    className={`rounded-full border px-3 py-1 text-sm transition-colors ${logCats[key] ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Severidade mínima</Label>
              <select
                value={logMinSev}
                onChange={(e) => setLogMinSev(e.target.value)}
                className="h-9 w-full max-w-xs rounded-lg border border-border bg-secondary/40 px-3 text-sm text-foreground focus:border-primary/50 focus:outline-none"
              >
                <option value="info">Info (tudo)</option>
                <option value="warning">Atenção e acima</option>
                <option value="error">Somente erros/críticos</option>
              </select>
            </div>

            <div className="flex justify-end border-t border-border pt-4">
              <Button onClick={() => toast({ title: 'Configuração salva (prévia)', description: 'A persistência entra quando ligarmos a auditoria no backend.' })}>
                <Save className="mr-2 h-4 w-4" /> Salvar
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Autenticação AD */}
      {user?.is_admin && tab === 'auth' && <LdapSettingsCard />}

      {/* Sistema — Atualizações */}
      {user?.is_admin && tab === 'sistema' && <SystemUpdateCard />}
      </div>
    </div>
  )
}
