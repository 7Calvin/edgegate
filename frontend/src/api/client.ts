import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

const API_BASE_URL = '/api/v1'

export const api = axios.create({
  baseURL: API_BASE_URL,
  // Send the HttpOnly refresh-token cookie on auth requests (H3).
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - add auth token
api.interceptors.request.use(
  (config) => {
    const { accessToken } = useAuthStore.getState()
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle 401 and refresh token
// Shared refresh promise to prevent concurrent refresh race conditions
let refreshPromise: Promise<string> | null = null

// Session is gone (refresh failed / no refresh token) -> send the user to the login
// portal instead of leaving a half-broken, downgraded UI.
function redirectToLogin() {
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Never try to refresh the refresh/logout calls themselves (avoids a loop).
    const isAuthEndpoint =
      originalRequest.url?.includes('/auth/refresh') ||
      originalRequest.url?.includes('/auth/logout')

    if (error.response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true

      const { logout } = useAuthStore.getState()

      try {
        // Refresh using the HttpOnly cookie — no token lives in JS (H3).
        // withCredentials sends the cookie; a shared promise coalesces
        // concurrent refreshes into one.
        if (!refreshPromise) {
          refreshPromise = axios
            .post(`${API_BASE_URL}/auth/refresh`, {}, { withCredentials: true })
            .then((response) => {
              // /auth/refresh returns the access token only (no user, no refresh
              // in the body). Update just the access token to avoid clobbering
              // the loaded user (the idle-refresh admin-downgrade bug).
              const { access_token } = response.data
              useAuthStore.setState({
                accessToken: access_token,
                isAuthenticated: true,
              })
              return access_token
            })
            .finally(() => {
              refreshPromise = null
            })
        }

        const newToken = await refreshPromise
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      } catch {
        refreshPromise = null
        logout()
        redirectToLogin()
      }
    }

    return Promise.reject(error)
  }
)

// Auth API
export const authApi = {
  login: (username: string, password: string, mfaCode?: string) =>
    api.post('/auth/login', { username, password, mfa_code: mfaCode }),

  logout: () => api.post('/auth/logout'),

  me: () => api.get('/auth/me'),

  // Refresh via the HttpOnly cookie (H3) — no token argument.
  refresh: () => api.post('/auth/refresh', {}),

  setupMfa: () => api.post('/auth/mfa/setup'),

  verifyMfa: (code: string) => api.post('/auth/mfa/verify', { code }),

  disableMfa: (password: string, mfaCode?: string) =>
    api.post('/auth/mfa/disable', mfaCode ? { password, mfa_code: mfaCode } : { password }),

  changePassword: (currentPassword: string, newPassword: string, confirmPassword: string) =>
    api.post('/auth/password/change', {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),

  // Server-observed client IP (as resolved through the trusted proxy chain).
  // Used by the Trusted Hosts editor to warn about locking yourself out.
  whoami: () => api.get<{ client_ip: string | null }>('/auth/whoami'),
}

// Users API
export const usersApi = {
  list: (params?: { page?: number; per_page?: number; search?: string; auth_source?: 'ad' | 'local'; is_admin?: boolean }) =>
    api.get('/users', { params }),

  get: (id: string) => api.get(`/users/${id}`),

  create: (data: {
    username: string
    password: string
    user_type?: 'human' | 'service'
    is_admin?: boolean
    description?: string
    allowed_source_ips?: string[]
  }) => api.post('/users', data),

  update: (id: string, data: Partial<{ email: string; is_active: boolean; is_admin: boolean }>) =>
    api.patch(`/users/${id}`, data),

  // Trusted Hosts: replace the source IP/CIDR allowlist for an admin or service
  // account. Dedicated endpoint (not the generic PATCH) so it can be audited and
  // guarded against self-lockout on the server side.
  updateTrustedHosts: (id: string, allowed_source_ips: string[]) =>
    api.put<{ id: string; username: string; allowed_source_ips: string[] }>(
      `/users/${id}/trusted-hosts`,
      { allowed_source_ips },
    ),

  delete: (id: string) => api.delete(`/users/${id}?permanent=true`),

  resetPassword: (id: string) => api.post(`/users/${id}/reset-password`),

  resetMfa: (id: string) => api.post(`/users/${id}/mfa/reset`),

  createServiceAccount: (data: {
    service_name: string
    service_description?: string
    is_admin?: boolean
    allowed_source_ips?: string[]
    expires_at?: string
  }) => api.post('/users/service-accounts', data),

  regenerateApiKey: (id: string) => api.post(`/users/service-accounts/${id}/regenerate-key`),

  stats: () => api.get('/users/stats/summary'),
}

// VPN API
export const vpnApi = {
  getProfile: () => api.get('/vpn/profile'),

  createProfile: () => api.post('/vpn/profile'),

  downloadConfig: () =>
    api.get('/vpn/config', { responseType: 'blob' }),

  // Download generic server config (no per-user certificates)
  downloadServerConfig: () =>
    api.get('/vpn/server/download', { responseType: 'blob' }),

  regenerateCertificate: () => api.post('/vpn/certificate/regenerate'),

  // Admin
  listProfiles: () => api.get('/vpn/profiles'),

  createProfileForUser: (userId: string) =>
    api.post(`/vpn/profiles/${userId}`, { user_id: userId }),

  updateProfile: (id: string, data: Partial<{ is_active: boolean }>) =>
    api.patch(`/vpn/profiles/${id}`, data),

  revokeProfile: (id: string, reason?: string) =>
    api.post(`/vpn/profiles/${id}/revoke`, null, { params: { reason } }),

  deleteProfile: (id: string) => api.delete(`/vpn/profiles/${id}`),

  serverStatus: () => api.get('/vpn/server/status'),

  startServer: () => api.post('/vpn/server/start'),

  stopServer: () => api.post('/vpn/server/stop'),

  restartServer: () => api.post('/vpn/server/restart'),

  changeNetwork: (data: { vpn_network: string; vpn_netmask: string }) =>
    api.put('/vpn/server/network', data),

  getActiveConnections: () => api.get('/vpn/server/connections'),

  disconnectClient: (username: string) => api.post(`/vpn/server/connections/${username}/disconnect`),

  getServerConfig: () => api.get('/vpn/server/config'),

  updateServerConfig: (data: {
    server_host?: string
    server_port?: number
    protocol?: string
    vpn_network?: string
    vpn_netmask?: string
    dns_servers?: string[]
    internal_dns_server?: string | null
    split_dns_domains?: string[]
    push_routes?: string[]
    redirect_gateway?: boolean
    compression?: boolean
    client_to_client?: boolean
    duplicate_cn?: boolean
    max_clients?: number
    keepalive_interval?: number
    keepalive_timeout?: number
  }) => api.put('/vpn/server/config', data),
}

// Firewall API
export const firewallApi = {
  listRules: () => api.get('/firewall/rules'),

  getRule: (id: string) => api.get(`/firewall/rules/${id}`),

  createRule: (data: {
    name: string
    action: string
    protocol?: string
    source_network?: string
    destination_network?: string
    destination_port_range?: string
    priority?: number
  }) => api.post('/firewall/rules', data),

  updateRule: (id: string, data: Partial<{ name: string; is_active: boolean; priority: number }>) =>
    api.patch(`/firewall/rules/${id}`, data),

  deleteRule: (id: string) => api.delete(`/firewall/rules/${id}`),

  apply: () => api.post('/firewall/apply'),

  getConfig: () => api.get('/firewall/config'),

  getStatus: () => api.get('/firewall/status'),

  initDefaults: () => api.post('/firewall/init-defaults'),

  // Quick rules
  getQuickRules: () => api.get('/firewall/quick-rules'),

  toggleQuickRule: (ruleKey: string, networks?: string[]) =>
    api.post(`/firewall/quick-rules/${ruleKey}/toggle`, networks ? { networks } : {}),

  setQuickRuleNetworks: (ruleKey: string, networks: string[]) =>
    api.put(`/firewall/quick-rules/${ruleKey}/networks`, { networks }),

  // NAT/DNAT rules
  listNatRules: () => api.get('/firewall/nat'),

  createNatRule: (data: {
    name: string
    description?: string
    protocol?: string
    external_port: number
    internal_ip: string
    internal_port: number
    source_network?: string
  }) => api.post('/firewall/nat', data),

  updateNatRule: (id: string, data: Partial<{
    name: string
    description: string
    protocol: string
    external_port: number
    internal_ip: string
    internal_port: number
    source_network: string | null
    is_active: boolean
  }>) => api.patch(`/firewall/nat/${id}`, data),

  deleteNatRule: (id: string) => api.delete(`/firewall/nat/${id}`),
}

// Connections API
export const connectionsApi = {
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    api.get('/connections', { params }),

  active: () => api.get('/connections/active'),

  live: () => api.get('/connections/live'),

  my: () => api.get('/connections/my'),

  myActive: () => api.get('/connections/my/active'),

  get: (id: string) => api.get(`/connections/${id}`),

  disconnect: (id: string) => api.post(`/connections/${id}/disconnect`),

  disconnectUser: (userId: string) =>
    api.post(`/connections/user/${userId}/disconnect`),

  stats: () => api.get('/connections/stats/summary'),

  bandwidth: () => api.get('/connections/stats/bandwidth'),

  throughput: (window: '1h' | '6h' | '24h' | '7d' = '24h', source: 'openvpn' | 'ipsec' | 'total' = 'openvpn') =>
    api.get('/connections/throughput', { params: { window, source } }),

  userStats: (userId: string) => api.get(`/connections/stats/user/${userId}`),

  myStats: () => api.get('/connections/my/stats'),

  cleanup: () => api.post('/connections/cleanup'),
}

// Admin API
export const adminApi = {
  dashboard: () => api.get('/admin/dashboard'),

  auditLogs: (params?: { page?: number; page_size?: number; category?: string; severity?: string; search?: string; since?: string }) =>
    api.get('/admin/audit-logs', { params }),

  systemHealth: () => api.get('/admin/system/health'),

  systemConfig: () => api.get('/admin/system/config'),

  // LDAP / Active Directory
  getLdapSettings: () => api.get<LdapSettings>('/admin/ldap-settings'),
  updateLdapSettings: (data: LdapSettingsUpdate) =>
    api.put<LdapSettings>('/admin/ldap-settings', data),
  testLdapSettings: (data: LdapTestRequest) =>
    api.post<LdapTestResult>('/admin/ldap-settings/test', data),
  syncLdapGroup: (params: { delete_mode: string; dry_run: boolean }) =>
    api.post<LdapSyncResult>('/admin/ldap-settings/sync-group', null, { params }),

  // NAT gateway (host-as-NAT)
  getNatGateway: () => api.get<NatGatewaySettings>('/admin/nat-gateway'),
  updateNatGateway: (data: NatGatewayUpdate) =>
    api.put<NatGatewaySettings>('/admin/nat-gateway', data),
}

export interface NatGatewaySettings {
  enabled: boolean
  network: string | null
  public_interface: string | null
  exclude_networks: string | null
  auto_excludes?: string[]
  applied?: boolean | null
  agent_message?: string | null
}

export interface NatGatewayUpdate {
  enabled: boolean
  network?: string | null
  public_interface?: string | null
  exclude_networks?: string | null
}

export interface LdapSettings {
  enabled: boolean
  server: string | null
  port: number
  use_ntlm: boolean
  ad_domain: string | null
  bind_dn: string | null
  bind_password_set: boolean
  search_base: string | null
  user_attr: string
  required_group_dn: string | null
  timeout: number
}

export interface LdapSettingsUpdate {
  enabled: boolean
  server?: string | null
  port: number
  use_ntlm: boolean
  ad_domain?: string | null
  bind_dn?: string | null
  bind_password?: string | null
  search_base?: string | null
  user_attr: string
  required_group_dn?: string | null
  timeout: number
}

export interface LdapTestRequest {
  server?: string | null
  port: number
  use_ntlm: boolean
  ad_domain?: string | null
  bind_dn?: string | null
  bind_password?: string | null
  search_base?: string | null
  timeout: number
}

export interface LdapTestResult {
  success: boolean
  message: string | null
}

export interface LdapSyncResult {
  success: boolean
  message: string | null
  dry_run: boolean
  delete_mode: string
  total_in_group: number
  added: number
  removed: number
  reactivated: number
  skipped: number
  added_users: string[]
  removed_users: string[]
}

// Proxy API (Reverse Proxy / Traefik)
export const proxyApi = {
  // Routes CRUD
  list: (params?: { page?: number; per_page?: number; is_enabled?: boolean }) =>
    api.get('/proxy/routes', { params }),

  get: (id: string) => api.get(`/proxy/routes/${id}`),

  create: (data: {
    name: string
    hostname: string
    backend_url: string
    path_prefix?: string
    strip_prefix?: boolean
    ssl_mode?: string
    force_https?: boolean
    health_check_type?: string
    health_check_path?: string
    health_check_interval?: string
    pass_host_header?: boolean
    custom_request_headers?: string
    custom_response_headers?: string
    rate_limit_average?: number
    rate_limit_burst?: number
    is_enabled?: boolean
  }) => api.post('/proxy/routes', data),

  update: (id: string, data: Partial<{
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
    rate_limit_average: number
    rate_limit_burst: number
    is_enabled: boolean
  }>) => api.put(`/proxy/routes/${id}`, data),

  delete: (id: string) => api.delete(`/proxy/routes/${id}`),

  // Config
  apply: () => api.post('/proxy/apply'),

  previewConfig: () => api.get('/proxy/config/preview'),

  // Status
  status: () => api.get('/proxy/status'),

  // Health checks
  healthCheckAll: () => api.post('/proxy/health-check'),

  healthCheck: (id: string) => api.post(`/proxy/routes/${id}/health-check`),

  // SSL Certificates
  certificates: () => api.get('/proxy/certificates'),

  certificateDetails: (domain: string) => api.get(`/proxy/certificates/${domain}`),

  renewCertificate: (domain: string) => api.post(`/proxy/certificates/${domain}/renew`),

  reissueCertificate: (domain: string) => api.post(`/proxy/certificates/${domain}/reissue`),

  deleteCertificate: (domain: string) => api.delete(`/proxy/certificates/${domain}`),

  // Management domain
  getManagementDomain: () => api.get('/proxy/management-domain'),

  updateManagementDomain: (data: { domain: string }) =>
    api.put('/proxy/management-domain', data),
}

// ACME DNS-01 API
export const acmeApi = {
  requestDnsChallenge: (data: { domain: string; proxy_route_id?: string }) =>
    api.post('/acme/request-dns', data),

  verifyDnsChallenge: (challengeId: string) =>
    api.post(`/acme/${challengeId}/verify`),

  listChallenges: (params?: { challenge_status?: string; page?: number; per_page?: number }) =>
    api.get('/acme/challenges', { params }),

  getChallenge: (challengeId: string) =>
    api.get(`/acme/challenges/${challengeId}`),

  deleteChallenge: (challengeId: string) =>
    api.delete(`/acme/challenges/${challengeId}`),
}

// IPsec API
export const ipsecApi = {
  // Connections CRUD
  list: (params?: { page?: number; per_page?: number; is_enabled?: boolean }) =>
    api.get('/ipsec/connections', { params }),

  get: (id: string) => api.get(`/ipsec/connections/${id}`),

  create: (data: {
    name: string
    description?: string
    left_ip: string
    left_subnet: string
    left_id: string
    right_ip: string
    right_ip_backup?: string
    right_subnet: string
    right_id: string
    auth_method?: string
    psk?: string
    ike_version?: string
    ike_cipher?: string
    ike_lifetime?: string
    esp_cipher?: string
    key_lifetime?: string
    auto_start?: boolean
    dpd_action?: string
    is_enabled?: boolean
  }) => api.post('/ipsec/connections', data),

  update: (id: string, data: Partial<{
    name: string
    description: string
    left_ip: string
    left_subnet: string
    left_id: string
    right_ip: string
    right_ip_backup?: string
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
  }>) => api.put(`/ipsec/connections/${id}`, data),

  delete: (id: string) => api.delete(`/ipsec/connections/${id}`),

  // Connection control
  start: (id: string) => api.post(`/ipsec/connections/${id}/start`),

  stop: (id: string) => api.post(`/ipsec/connections/${id}/stop`),

  restart: (id: string) => api.post(`/ipsec/connections/${id}/restart`),

  // HA / failover controls
  switchBackup: (id: string) => api.post(`/ipsec/connections/${id}/switch-backup`),
  rollbackPrimary: (id: string) => api.post(`/ipsec/connections/${id}/rollback-primary`),
  testFailover: (id: string) => api.post(`/ipsec/connections/${id}/test-failover`),

  // Global status & control
  status: () => api.get('/ipsec/status'),

  connectionStatus: (name: string) => api.get(`/ipsec/status/${name}`),

  reload: () => api.post('/ipsec/reload'),

  apply: () => api.post('/ipsec/apply'),

  restartStrongSwan: () => api.post('/ipsec/restart'),

  // Config preview
  previewConfig: () => api.get('/ipsec/config/preview'),

  // Generated swanctl config for a single connection (PSK masked), as plain text
  connectionConfig: (id: string) => api.get(`/ipsec/connections/${id}/config`, { responseType: 'text' }),

  // Export the connection for a peer device (fortigate CLI / generic params), as text
  exportConfig: (id: string, params: Record<string, string>) =>
    api.get(`/ipsec/connections/${id}/export`, { params, responseType: 'text' }),

  // Utility
  version: () => api.get('/ipsec/version'),

  syncStatus: () => api.post('/ipsec/sync-status'),

  // Server info for auto-filling Local Gateway fields
  serverInfo: () => api.get('/ipsec/server-info'),

  // Detailed status and logs
  statusAll: () => api.get('/ipsec/statusall'),

  logs: (lines: number = 100, connection?: string) =>
    api.get('/ipsec/logs', { params: { lines, connection } }),
}

// System / Update API
export interface UpdateStatus {
  state: 'idle' | 'running' | 'done' | 'failed' | 'rolled_back'
  pct: number
  message: string
  error?: string
  ref?: string
  updated_at?: string
  log_tail?: string[]
}

export const systemApi = {
  // Running version for the badge (any authenticated user).
  version: () => api.get('/system/version'),
  info: () => api.get('/system/info'),

  // Admin: fetch upstream and check whether a newer version exists.
  checkUpdate: () => api.get('/system/update/check'),

  // Admin: list available version tags (to update to / roll back to a specific one).
  listVersions: () => api.get('/system/update/versions'),

  // Admin: kick off the update. Returns a job id immediately.
  startUpdate: (payload?: { ref?: string; backup?: boolean; run_migrations?: boolean }) =>
    api.post('/system/update', payload ?? {}),

  // Admin: explicitly regenerate OpenVPN server.conf (PKI/certs preserved).
  regenerateOpenvpnConfig: () => api.post('/system/openvpn/regenerate-config'),

  // Admin: download a full backup (DB + OpenVPN PKI + config) as a .tar.gz blob.
  downloadBackup: () => api.get('/system/backup', { responseType: 'blob' }),

  // Admin: upload a backup .tar.gz and restore it (DESTRUCTIVE). Progress is polled
  // from the host agent via agentStatus(), same as an update.
  restore: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/system/restore', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },

  // Resilient progress polling: hits the host update-agent DIRECTLY through
  // Traefik (`/update-agent/status`), bypassing the backend — which restarts
  // mid-update. Traefik injects the agent token, so no auth header is needed
  // here. Tolerant of transient network errors during the restart window.
  agentStatus: async (): Promise<UpdateStatus | null> => {
    try {
      const res = await fetch('/update-agent/status', { cache: 'no-store' })
      if (!res.ok) return null
      return (await res.json()) as UpdateStatus
    } catch {
      return null
    }
  },
}
