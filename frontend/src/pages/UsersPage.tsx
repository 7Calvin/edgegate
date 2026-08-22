import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { formatDateTime } from '@/lib/tz'
import { Plus, Search, UserCheck, UserX, Key, X, Eye, EyeOff, Server, User as UserIcon, Trash2, Copy, Check, AlertTriangle, ShieldCheck, ShieldOff, Network, Shield, ChevronDown, ChevronRight } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { TrustedHostsModal } from '@/components/TrustedHostsModal'
import { parseHostEntry } from '@/lib/cidr'
import type { User } from '@/types'

export default function UsersPage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const currentUser = useAuthStore((state) => state.user)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<'all' | 'ad' | 'local' | 'admin'>('all')
  const [perPage, setPerPage] = useState(20)
  const [page, setPage] = useState(1)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [userType, setUserType] = useState<'human' | 'service'>('human')
  const [newUser, setNewUser] = useState({
    username: '',
    password: '',
    is_admin: false,
    description: '',
  })
  // Optional Trusted Hosts at creation (collapsed by default; empty = allow all)
  const [showTrustedHosts, setShowTrustedHosts] = useState(false)
  const [newTrustedHosts, setNewTrustedHosts] = useState<string[]>([])
  const [trustedHostDraft, setTrustedHostDraft] = useState('')

  // Delete confirmation modal state
  const [userToDelete, setUserToDelete] = useState<User | null>(null)
  const [deleteConfirmUsername, setDeleteConfirmUsername] = useState('')

  // Password reset modal state
  const [newPasswordInfo, setNewPasswordInfo] = useState<{ username: string; password: string } | null>(null)
  const [passwordCopied, setPasswordCopied] = useState(false)

  // API key modal state (for service accounts)
  const [apiKeyInfo, setApiKeyInfo] = useState<{ username: string; apiKey: string } | null>(null)
  const [apiKeyCopied, setApiKeyCopied] = useState(false)

  // Trusted Hosts editor (admins + service accounts)
  const [trustedHostsUser, setTrustedHostsUser] = useState<User | null>(null)

  const { data: users, isLoading } = useQuery({
    queryKey: ['users', search, typeFilter, page, perPage],
    queryFn: () =>
      usersApi
        .list({
          search: search || undefined,
          page,
          per_page: perPage,
          ...(typeFilter === 'ad'
            ? { auth_source: 'ad' as const }
            : typeFilter === 'local'
            ? { auth_source: 'local' as const }
            : typeFilter === 'admin'
            ? { is_admin: true }
            : {}),
        })
        .then((res) => res.data),
  })

  const toggleUserMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      usersApi.update(id, { is_active: isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast({ title: 'Usuário atualizado com sucesso' })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } } }
      const message = err.response?.data?.detail || 'Falha ao atualizar usuário'
      toast({
        variant: 'destructive',
        title: 'Não foi possível atualizar o usuário',
        description: message
      })
    },
  })

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, username }: { id: string; username: string }) =>
      usersApi.resetPassword(id).then(res => ({ ...res, username })),
    onSuccess: (response) => {
      setNewPasswordInfo({
        username: response.username,
        password: response.data.new_password,
      })
      setPasswordCopied(false)
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao redefinir a senha' })
    },
  })

  const deleteUserMutation = useMutation({
    mutationFn: (id: string) => usersApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast({ title: 'Usuário excluído com sucesso' })
      setUserToDelete(null)
      setDeleteConfirmUsername('')
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } } }
      toast({
        variant: 'destructive',
        title: 'Falha ao excluir usuário',
        description: err.response?.data?.detail || 'Erro desconhecido',
      })
    },
  })

  const createUserMutation = useMutation({
    mutationFn: (): Promise<import('axios').AxiosResponse> => {
      // Trusted Hosts only apply to admins and service accounts; don't attach
      // them to a plain VPN user where they'd be stored but never enforced.
      const trustedHosts = (userType === 'service' || newUser.is_admin) ? newTrustedHosts : []
      if (userType === 'service') {
        return usersApi.createServiceAccount({
          service_name: newUser.username,
          service_description: newUser.description || undefined,
          is_admin: newUser.is_admin,
          allowed_source_ips: trustedHosts,
        })
      }
      const payload = {
        username: newUser.username,
        password: newUser.password,
        user_type: userType as 'human' | 'service',
        is_admin: newUser.is_admin,
        description: newUser.description || undefined,
        allowed_source_ips: trustedHosts,
      }
      return usersApi.create(payload)
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      if (userType === 'service' && response.data.api_key) {
        setApiKeyInfo({
          username: response.data.username,
          apiKey: response.data.api_key,
        })
        setApiKeyCopied(false)
      } else {
        toast({ title: 'Usuário criado com sucesso' })
      }
      closeModal()
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string | { msg: string }[] } } }
      let message = 'Erro desconhecido'
      if (err.response?.data?.detail) {
        if (Array.isArray(err.response.data.detail)) {
          message = err.response.data.detail.map(e => e.msg).join('; ')
        } else {
          message = String(err.response.data.detail)
        }
      }
      toast({
        variant: 'destructive',
        title: 'Falha ao criar usuário',
        description: message,
      })
    },
  })

  const regenerateApiKeyMutation = useMutation({
    mutationFn: ({ id, username }: { id: string; username: string }) =>
      usersApi.regenerateApiKey(id).then(res => ({ ...res, username })),
    onSuccess: (response) => {
      setApiKeyInfo({
        username: response.username,
        apiKey: response.data.api_key,
      })
      setApiKeyCopied(false)
    },
    onError: () => {
      toast({ variant: 'destructive', title: 'Falha ao regenerar a chave de API' })
    },
  })

  const toggleAdminMutation = useMutation({
    mutationFn: ({ id, isAdmin }: { id: string; isAdmin: boolean }) =>
      usersApi.update(id, { is_admin: isAdmin }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast({ title: 'Função de administrador atualizada com sucesso' })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } } }
      const message = err.response?.data?.detail || 'Falha ao atualizar a função de administrador'
      toast({
        variant: 'destructive',
        title: 'Não foi possível atualizar a função de administrador',
        description: message,
      })
    },
  })

  const closeModal = () => {
    setShowCreateModal(false)
    setShowPassword(false)
    setUserType('human')
    setNewUser({ username: '', password: '', is_admin: false, description: '' })
    setShowTrustedHosts(false)
    setNewTrustedHosts([])
    setTrustedHostDraft('')
  }

  const addTrustedHostDraft = () => {
    const parsed = parseHostEntry(trustedHostDraft)
    if (!parsed) {
      toast({ variant: 'destructive', title: 'Endereço inválido', description: 'Use um IP ou CIDR (ex: 203.0.113.10 ou 10.0.0.0/24).' })
      return
    }
    if (!newTrustedHosts.includes(parsed.normalized)) {
      setNewTrustedHosts([...newTrustedHosts, parsed.normalized])
    }
    setTrustedHostDraft('')
  }

  const validatePassword = (password: string): string[] => {
    const errors: string[] = []
    if (password.length < 12) errors.push('Pelo menos 12 caracteres')
    if (!/[A-Z]/.test(password)) errors.push('Letra maiúscula')
    if (!/[a-z]/.test(password)) errors.push('Letra minúscula')
    if (!/\d/.test(password)) errors.push('Número')
    if (!/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password)) errors.push('Caractere especial')
    return errors
  }

  const handleCreateUser = () => {
    if (!newUser.username) {
      toast({ variant: 'destructive', title: 'O nome de usuário é obrigatório' })
      return
    }
    if (userType === 'human') {
      if (!newUser.password) {
        toast({ variant: 'destructive', title: 'A senha é obrigatória' })
        return
      }
      const pwErrors = validatePassword(newUser.password)
      if (pwErrors.length > 0) {
        toast({
          variant: 'destructive',
          title: 'Requisitos de senha não atendidos',
          description: `Faltando: ${pwErrors.join(', ')}`,
        })
        return
      }
    }
    createUserMutation.mutate()
  }

  const userList = users?.items || []
  const total = users?.total ?? userList.length
  const totalPages = Math.max(1, Math.ceil(total / perPage))
  const fromItem = total === 0 ? 0 : (page - 1) * perPage + 1
  const toItem = Math.min(page * perPage, total)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Usuários"
        subtitle="Gerencie as contas de acesso"
        actions={
          <Button onClick={() => setShowCreateModal(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Adicionar Usuário
          </Button>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por nome..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            className="pl-9"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value as 'all' | 'ad' | 'local' | 'admin'); setPage(1) }}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="all">Todos os tipos</option>
          <option value="ad">AD</option>
          <option value="local">Local</option>
          <option value="admin">Admin</option>
        </select>
        <select
          value={perPage}
          onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1) }}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value={10}>10 / página</option>
          <option value={20}>20 / página</option>
          <option value={50}>50 / página</option>
        </select>
      </div>

      {/* Users Table */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="text-base">Todos os Usuários</CardTitle>
          <CardDescription className="text-xs">
            {total} usuário{total === 1 ? '' : 's'} no total
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : userList.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">Nenhum usuário encontrado</p>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-3 text-left">Usuário</th>
                    <th className="px-4 py-3 text-left">Tipo</th>
                    <th className="px-4 py-3 text-left">Descrição</th>
                    <th className="px-4 py-3 text-left">MFA</th>
                    <th className="px-4 py-3 text-left">Último Acesso</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {userList.map((user: User) => (
                    <tr key={user.id} className="border-b">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className={`p-1.5 rounded ${user.user_type === 'service' ? 'bg-primary/20' : 'bg-primary/20'}`}>
                            {user.user_type === 'service' ? (
                              <Server className="h-4 w-4 text-primary" />
                            ) : (
                              <UserIcon className="h-4 w-4 text-primary" />
                            )}
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5">
                              <p className="font-medium">{user.username}</p>
                              {user.auth_source === 'ad' && (
                                <span
                                  className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-medium text-sky-400"
                                  title="Usuário sincronizado do Active Directory"
                                >
                                  <Network className="h-3 w-3" /> AD
                                </span>
                              )}
                            </div>
                            <p className="text-muted-foreground text-xs">
                              {user.email || (user.auth_source === 'ad' ? 'Active Directory' : user.user_type === 'service' ? 'Conta de Serviço' : '-')}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded ${
                            user.user_type === 'service'
                              ? 'bg-primary/20 text-primary'
                              : 'bg-primary/20 text-primary'
                          }`}>
                            {user.user_type === 'service' ? 'Serviço' : 'Humano'}
                          </span>
                          <button
                            onClick={() => {
                              if (user.id === currentUser?.id || user.auth_source === 'ad') return
                              toggleAdminMutation.mutate({
                                id: user.id,
                                isAdmin: !user.is_admin,
                              })
                            }}
                            disabled={user.id === currentUser?.id || toggleAdminMutation.isPending || user.auth_source === 'ad'}
                            className={`inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded transition-colors ${
                              user.id === currentUser?.id || user.auth_source === 'ad'
                                ? 'cursor-not-allowed opacity-50'
                                : 'cursor-pointer hover:opacity-80'
                            } ${
                              user.is_admin
                                ? 'bg-warning/20 text-warning'
                                : 'bg-muted text-muted-foreground'
                            }`}
                            title={
                              user.auth_source === 'ad'
                                ? 'Função gerenciada pelo Active Directory'
                                : user.id === currentUser?.id
                                ? 'Não é possível alterar sua própria função de administrador'
                                : user.is_admin
                                  ? 'Clique para remover a função de administrador'
                                  : 'Clique para conceder a função de administrador'
                            }
                          >
                            {user.is_admin ? (
                              <>
                                <ShieldCheck className="h-3 w-3" /> Admin
                              </>
                            ) : (
                              <>
                                <ShieldOff className="h-3 w-3" /> Usuário
                              </>
                            )}
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground max-w-48 truncate">
                        {user.service_description || '-'}
                      </td>
                      <td className="px-4 py-3">
                        {user.user_type === 'service' ? (
                          <span className="text-muted-foreground">N/A</span>
                        ) : (
                          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${user.mfa_enabled ? 'bg-success/15 text-success' : 'bg-destructive/15 text-destructive'}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${user.mfa_enabled ? 'bg-success' : 'bg-destructive'}`} />
                            {user.mfa_enabled ? 'Habilitado' : 'Desabilitado'}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {user.last_login_at ? formatDateTime(user.last_login_at) : 'Nunca'}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => {
                            if (user.id === currentUser?.id) return
                            toggleUserMutation.mutate({
                              id: user.id,
                              isActive: !user.is_active,
                            })
                          }}
                          disabled={user.id === currentUser?.id}
                          className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
                            user.id === currentUser?.id
                              ? 'cursor-not-allowed opacity-50'
                              : 'cursor-pointer hover:opacity-80'
                          } ${
                            user.is_active
                              ? 'bg-success/20 text-success'
                              : 'bg-destructive/20 text-destructive'
                          }`}
                          title={user.id === currentUser?.id ? 'Não é possível desativar a si mesmo' : (user.is_active ? 'Clique para desativar' : 'Clique para ativar')}
                        >
                          {user.is_active ? (
                            <>
                              <UserCheck className="h-3 w-3" /> Ativo
                            </>
                          ) : (
                            <>
                              <UserX className="h-3 w-3" /> Inativo
                            </>
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {user.auth_source === 'ad' ? (
                          <span
                            className="pr-2 text-xs text-muted-foreground"
                            title="Conta gerenciada pelo Active Directory — senha e exclusão são controladas no AD"
                          >
                            Gerenciado no AD
                          </span>
                        ) : (
                        <div className="flex justify-end gap-1">
                          {(user.user_type === 'service' || user.is_admin) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              title="Trusted Hosts (restringir IPs de origem)"
                              onClick={() => setTrustedHostsUser(user)}
                            >
                              <Shield className="h-4 w-4" />
                            </Button>
                          )}
                          {user.user_type === 'service' ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              title="Regenerar Chave de API"
                              onClick={() => regenerateApiKeyMutation.mutate({ id: user.id, username: user.username })}
                            >
                              <Key className="h-4 w-4" />
                            </Button>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              title="Redefinir senha"
                              onClick={() => resetPasswordMutation.mutate({ id: user.id, username: user.username })}
                            >
                              <Key className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            title={user.id === currentUser?.id ? 'Não é possível excluir a si mesmo' : 'Excluir usuário'}
                            onClick={() => setUserToDelete(user)}
                            disabled={user.id === currentUser?.id}
                            className={user.id === currentUser?.id ? 'opacity-50 cursor-not-allowed' : 'hover:text-destructive'}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {total > perPage && (
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 text-sm text-muted-foreground">
              <span>Mostrando {fromItem}–{toItem} de {total}</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  Anterior
                </Button>
                <span>Página {page} de {totalPages}</span>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
                  Próxima
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold">Criar Novo Usuário</h2>
              <Button variant="ghost" size="sm" onClick={closeModal}>
                <X className="h-4 w-4" />
              </Button>
            </div>

            {/* User Type Selection */}
            <div className="flex gap-2">
              <Button
                variant={userType === 'human' ? 'default' : 'outline'}
                onClick={() => setUserType('human')}
                className="flex-1"
              >
                Usuário Humano
              </Button>
              <Button
                variant={userType === 'service' ? 'default' : 'outline'}
                onClick={() => setUserType('service')}
                className="flex-1"
              >
                Conta de Serviço
              </Button>
            </div>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="new-username">
                  {userType === 'service' ? 'Nome do Servidor' : 'Nome de Usuário'}
                </Label>
                <Input
                  id="new-username"
                  value={newUser.username}
                  onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                  placeholder={userType === 'service' ? 'server-backup-01' : 'john_doe'}
                />
                <p className="text-xs text-muted-foreground">Apenas letras, números, sublinhado e hífen</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Descrição (opcional)</Label>
                <Input
                  id="description"
                  value={newUser.description}
                  onChange={(e) => setNewUser({ ...newUser, description: e.target.value })}
                  placeholder={userType === 'service' ? 'Servidor de backup - datacenter 1' : 'Departamento de TI - João'}
                />
              </div>

              {userType === 'human' && (
                <div className="space-y-2">
                  <Label htmlFor="new-password">Senha</Label>
                  <div className="relative">
                    <Input
                      id="new-password"
                      type={showPassword ? 'text' : 'password'}
                      value={newUser.password}
                      onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                      placeholder="Digite a senha"
                      className="pr-10"
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
                  <div className="text-xs text-muted-foreground space-y-1">
                    <p>Requisitos da senha:</p>
                    <ul className="list-disc list-inside">
                      <li className={newUser.password.length >= 12 ? 'text-success' : ''}>Pelo menos 12 caracteres</li>
                      <li className={/[A-Z]/.test(newUser.password) ? 'text-success' : ''}>Letra maiúscula</li>
                      <li className={/[a-z]/.test(newUser.password) ? 'text-success' : ''}>Letra minúscula</li>
                      <li className={/\d/.test(newUser.password) ? 'text-success' : ''}>Número</li>
                      <li className={/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(newUser.password) ? 'text-success' : ''}>Caractere especial (!@#$%^&*...)</li>
                    </ul>
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="new-admin"
                  checked={newUser.is_admin}
                  onChange={(e) => setNewUser({ ...newUser, is_admin: e.target.checked })}
                  className="h-4 w-4"
                />
                <Label htmlFor="new-admin">Administrador</Label>
              </div>

              {(userType === 'service' || newUser.is_admin) && (
                <div className="rounded-md border">
                  <button
                    type="button"
                    onClick={() => setShowTrustedHosts((v) => !v)}
                    className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium"
                  >
                    <span className="flex items-center gap-2">
                      <Shield className="h-4 w-4" /> Trusted Hosts (opcional)
                      {newTrustedHosts.length > 0 && (
                        <span className="rounded-full bg-primary/20 px-1.5 text-xs text-primary">{newTrustedHosts.length}</span>
                      )}
                    </span>
                    {showTrustedHosts ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </button>
                  {showTrustedHosts && (
                    <div className="space-y-2 border-t p-3">
                      <p className="text-xs text-muted-foreground">
                        Restringe os IPs de origem permitidos (IP ou CIDR). Vazio = <span className="font-medium">libera qualquer IP</span>.
                      </p>
                      <div className="flex gap-2">
                        <Input
                          value={trustedHostDraft}
                          onChange={(e) => setTrustedHostDraft(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTrustedHostDraft() } }}
                          placeholder="203.0.113.10  ou  10.0.0.0/24"
                          className="font-mono"
                        />
                        <Button type="button" variant="outline" onClick={addTrustedHostDraft}>
                          <Plus className="h-4 w-4" />
                        </Button>
                      </div>
                      {newTrustedHosts.length > 0 && (
                        <ul className="space-y-1">
                          {newTrustedHosts.map((h) => (
                            <li key={h} className="flex items-center justify-between rounded border bg-muted/40 px-2 py-1">
                              <span className="font-mono text-xs">{h}</span>
                              <button
                                type="button"
                                onClick={() => setNewTrustedHosts(newTrustedHosts.filter((x) => x !== h))}
                                className="text-muted-foreground hover:text-destructive"
                                title="Remover"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div className="bg-muted p-3 rounded text-sm">
                {userType === 'service' ? (
                  <>
                    <p className="font-medium">Conta de Serviço</p>
                    <p className="text-muted-foreground">
                      Uma chave de API será gerada automaticamente. Armazene-a com segurança — ela será exibida apenas uma vez.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="font-medium">Usuário Humano</p>
                    <p className="text-muted-foreground">
                      Conta de usuário comum para conexões VPN manuais.
                    </p>
                  </>
                )}
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-4">
              <Button variant="outline" onClick={closeModal}>
                Cancelar
              </Button>
              <Button
                onClick={handleCreateUser}
                disabled={createUserMutation.isPending}
              >
                {createUserMutation.isPending ? 'Criando...' : 'Criar'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {userToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center gap-3 text-destructive">
              <AlertTriangle className="h-6 w-6" />
              <h2 className="text-xl font-bold">Excluir Usuário</h2>
            </div>

            <div className="space-y-3">
              <p className="text-muted-foreground">
                Esta ação não pode ser desfeita. Isso excluirá permanentemente o usuário
                <span className="font-mono font-bold text-foreground"> {userToDelete.username}</span>.
              </p>

              <div className="space-y-2">
                <Label htmlFor="confirm-username">
                  Digite <span className="font-mono font-bold">{userToDelete.username}</span> para confirmar:
                </Label>
                <Input
                  id="confirm-username"
                  value={deleteConfirmUsername}
                  onChange={(e) => setDeleteConfirmUsername(e.target.value)}
                  placeholder="Digite o nome de usuário para confirmar"
                  className="font-mono"
                />
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-4">
              <Button
                variant="outline"
                onClick={() => {
                  setUserToDelete(null)
                  setDeleteConfirmUsername('')
                }}
              >
                Cancelar
              </Button>
              <Button
                variant="destructive"
                onClick={() => deleteUserMutation.mutate(userToDelete.id)}
                disabled={deleteConfirmUsername !== userToDelete.username || deleteUserMutation.isPending}
              >
                {deleteUserMutation.isPending ? 'Excluindo...' : 'Excluir Usuário'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* New Password Modal */}
      {newPasswordInfo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center gap-3 text-success">
              <Key className="h-6 w-6" />
              <h2 className="text-xl font-bold">Senha Redefinida</h2>
            </div>

            <div className="space-y-3">
              <p className="text-muted-foreground">
                Nova senha gerada para <span className="font-bold text-foreground">{newPasswordInfo.username}</span>:
              </p>

              <div className="flex items-center gap-2">
                <Input
                  value={newPasswordInfo.password}
                  readOnly
                  className="font-mono text-lg"
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    navigator.clipboard.writeText(newPasswordInfo.password)
                    setPasswordCopied(true)
                    toast({ title: 'Senha copiada para a área de transferência' })
                  }}
                  title="Copiar senha"
                >
                  {passwordCopied ? (
                    <Check className="h-4 w-4 text-success" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>

              <p className="text-xs text-warning">
                Certifique-se de copiar esta senha agora. Você não poderá vê-la novamente.
              </p>
            </div>

            <div className="flex justify-end pt-4">
              <Button onClick={() => setNewPasswordInfo(null)}>
                Fechar
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* API Key Modal (service accounts) */}
      {apiKeyInfo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center gap-3 text-success">
              <Key className="h-6 w-6" />
              <h2 className="text-xl font-bold">Chave de API</h2>
            </div>

            <div className="space-y-3">
              <p className="text-muted-foreground">
                Chave de API para a conta de serviço <span className="font-bold text-foreground">{apiKeyInfo.username}</span>:
              </p>

              <div className="flex items-center gap-2">
                <Input
                  value={apiKeyInfo.apiKey}
                  readOnly
                  className="font-mono text-sm"
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    navigator.clipboard.writeText(apiKeyInfo.apiKey)
                    setApiKeyCopied(true)
                    toast({ title: 'Chave de API copiada para a área de transferência' })
                  }}
                  title="Copiar chave de API"
                >
                  {apiKeyCopied ? (
                    <Check className="h-4 w-4 text-success" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>

              <p className="text-xs text-warning">
                Armazene esta chave de API com segurança. Ela não será exibida novamente.
              </p>
            </div>

            <div className="flex justify-end pt-4">
              <Button onClick={() => setApiKeyInfo(null)}>
                Fechar
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Trusted Hosts editor */}
      {trustedHostsUser && (
        <TrustedHostsModal
          user={trustedHostsUser}
          isSelf={trustedHostsUser.id === currentUser?.id}
          onClose={() => setTrustedHostsUser(null)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['users'] })}
        />
      )}
    </div>
  )
}
