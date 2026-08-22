import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'
import { LogoMark } from '@/components/Logo'
import { Loader2 } from 'lucide-react'

const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
  mfaCode: z.string().optional(),
})

type LoginForm = z.infer<typeof loginSchema>

export default function LoginPage() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { isAuthenticated, setAuth, setMfaPending } = useAuthStore()
  const [isLoading, setIsLoading] = useState(false)
  const [showMfa, setShowMfa] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
    getValues,
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
  })

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard')
    }
  }, [isAuthenticated, navigate])

  const onSubmit = async (data: LoginForm) => {
    setIsLoading(true)
    try {
      const response = await authApi.login(data.username, data.password, data.mfaCode)
      const { access_token, refresh_token, user_id, username, is_admin, mfa_enabled, mfa_required, mfa_pending } = response.data

      // Build user object from flat response fields
      // The full user object will be fetched by checkAuth() if needed
      const user = {
        id: user_id,
        username,
        is_admin,
        mfa_enabled: mfa_enabled ?? false,
        mfa_required: mfa_required ?? false,
        email: '',
        user_type: is_admin ? 'admin' : 'human',
        is_active: true,
        max_concurrent_connections: 1,
        created_at: new Date().toISOString(),
      } as const

      // mfa_pending means user has MFA enabled and needs to verify
      // If mfa_pending is false, user can login (MFA not yet set up)
      if (mfa_pending && !data.mfaCode) {
        setShowMfa(true)
        setMfaPending(true)
        toast({
          title: 'MFA Required',
          description: 'Please enter your MFA code',
        })
      } else {
        setAuth(user, access_token, refresh_token)
        toast({
          title: 'Welcome!',
          description: `Logged in as ${username}`,
        })
        navigate('/dashboard')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      toast({
        variant: 'destructive',
        title: 'Login failed',
        description: err.response?.data?.message || 'Invalid credentials',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleMfaSubmit = async () => {
    const values = getValues()
    await onSubmit(values)
  }

  return (
    <div className="relative min-h-screen flex items-center justify-center bg-background p-4 overflow-hidden">
      {/* ambient glow */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-96 w-[36rem] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />
      <Card className="relative w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mb-4 flex justify-center">
            <LogoMark size={60} />
          </div>
          <CardTitle className="text-2xl">Edge<span className="text-primary">Gate</span></CardTitle>
          <CardDescription>
            {showMfa ? 'Digite seu código MFA' : 'Entre na sua conta'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {!showMfa ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="username">Usuário</Label>
                  <Input
                    id="username"
                    type="text"
                    placeholder="Digite seu usuário"
                    {...register('username')}
                    disabled={isLoading}
                  />
                  {errors.username && (
                    <p className="text-sm text-destructive">{errors.username.message}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">Senha</Label>
                  <Input
                    id="password"
                    type="password"
                    placeholder="Digite sua senha"
                    {...register('password')}
                    disabled={isLoading}
                  />
                  {errors.password && (
                    <p className="text-sm text-destructive">{errors.password.message}</p>
                  )}
                </div>
              </>
            ) : (
              <div className="space-y-2">
                <Label htmlFor="mfaCode">MFA Code</Label>
                <Input
                  id="mfaCode"
                  type="text"
                  placeholder="Enter 6-digit code"
                  maxLength={6}
                  {...register('mfaCode')}
                  disabled={isLoading}
                />
                {errors.mfaCode && (
                  <p className="text-sm text-destructive">{errors.mfaCode.message}</p>
                )}
              </div>
            )}
            <Button
              type={showMfa ? 'button' : 'submit'}
              className="w-full"
              disabled={isLoading}
              onClick={showMfa ? handleMfaSubmit : undefined}
            >
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {showMfa ? 'Verificar MFA' : 'Entrar'}
            </Button>
            {showMfa && (
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => {
                  setShowMfa(false)
                  setMfaPending(false)
                }}
              >
                Voltar ao login
              </Button>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
