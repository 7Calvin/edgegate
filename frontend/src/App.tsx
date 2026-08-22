import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { Toaster } from '@/components/ui/toaster'

// Pages
import LoginPage from '@/pages/LoginPage'
import DashboardPage from '@/pages/DashboardPage'
import UsersPage from '@/pages/UsersPage'
import VPNPage from '@/pages/VPNPage'
import FirewallPage from '@/pages/FirewallPage'
import ConnectionsPage from '@/pages/ConnectionsPage'
import SettingsPage from '@/pages/SettingsPage'
import IPsecPage from '@/pages/IPsecPage'
import ReverseProxyPage from '@/pages/ReverseProxyPage'
import AuditPage from '@/pages/AuditPage'

// Layout
import DashboardLayout from '@/components/layout/DashboardLayout'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthStore()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuthStore()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  if (!user?.is_admin) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}

function App() {
  const { checkAuth } = useAuthStore()

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <DashboardLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="users" element={<AdminRoute><UsersPage /></AdminRoute>} />
          <Route path="vpn" element={<VPNPage />} />
          <Route path="firewall" element={<AdminRoute><FirewallPage /></AdminRoute>} />
          <Route path="ipsec" element={<AdminRoute><IPsecPage /></AdminRoute>} />
          <Route path="proxy" element={<AdminRoute><ReverseProxyPage /></AdminRoute>} />
          <Route path="connections" element={<AdminRoute><ConnectionsPage /></AdminRoute>} />
          <Route path="audit" element={<AdminRoute><AuditPage /></AdminRoute>} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
      <Toaster />
    </>
  )
}

export default App
