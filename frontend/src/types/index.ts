// User types
export interface User {
  id: string
  username: string
  email: string
  user_type: 'human' | 'service' | 'admin'
  auth_source?: 'local' | 'ad'
  is_active: boolean
  is_admin: boolean
  mfa_enabled: boolean
  mfa_required: boolean
  max_concurrent_connections: number
  bandwidth_limit_mbps?: number
  created_at: string
  last_login_at?: string
  service_name?: string
  service_description?: string
  // Trusted Hosts: source IPs/CIDRs allowed to authenticate against the panel /
  // API. Empty = no restriction. Not enforced for plain VPN (human) users.
  allowed_source_ips?: string[]
}

// Server-observed identity for the current request. Powers the anti-lockout
// hint in the Trusted Hosts editor ("your current IP is / isn't covered").
export interface WhoAmIResponse {
  client_ip: string | null
}

export interface UserCreate {
  username: string
  email: string
  password: string
  user_type?: 'human' | 'service' | 'admin'
  is_admin?: boolean
  max_concurrent_connections?: number
}

export interface ServiceAccountCreate {
  service_name: string
  service_description?: string
  is_admin?: boolean
  allowed_source_ips?: string[]
  max_concurrent_connections?: number
  bandwidth_limit_mbps?: number
  expires_at?: string
}

export interface ServiceAccountResponse {
  id: string
  username: string
  service_name: string
  service_description?: string
  user_type: 'service'
  is_active: boolean
  is_admin: boolean
  allowed_source_ips: string[]
  max_concurrent_connections: number
  bandwidth_limit_mbps?: number
  created_at: string
  expires_at?: string
  last_login_at?: string
  api_key_prefix?: string
  api_key?: string
}

export interface ApiKeyResponse {
  api_key: string
  key_prefix: string
  created_at: string
  message: string
}

// Auth types
export interface LoginRequest {
  username: string
  password: string
  mfa_code?: string
}

export interface LoginResponse {
  access_token: string
  refresh_token?: string | null  // H3: delivered as HttpOnly cookie, not in the body
  token_type: string
  expires_in: number
  user: User
  mfa_required: boolean
}

export interface MFASetupResponse {
  secret: string
  qr_code: string
  backup_codes: string[]
}

// VPN types
export interface VPNProfile {
  id: string
  user_id: string
  assigned_ip: string
  is_active: boolean
  is_revoked: boolean
  total_connections: number
  total_bytes_sent: number
  total_bytes_received: number
  last_connection_at?: string
  created_at: string
  certificate_expires_at?: string
}

export interface VPNServerStatus {
  is_running: boolean
  connected_clients: number
  total_bytes_in: number
  total_bytes_out: number
  uptime: number
}

export interface VPNServerConfig {
  server_host: string
  server_port: number
  protocol: string
  vpn_network: string
  vpn_netmask: string
  dns_servers: string[]
  internal_dns_server?: string | null
  split_dns_domains?: string[]
  push_routes: string[]
  redirect_gateway: boolean
  compression: boolean
  client_to_client: boolean
  duplicate_cn: boolean
  max_clients: number
  keepalive_interval: number
  keepalive_timeout: number
  network_editable: boolean
}

// Connection types
export interface Connection {
  id: string
  user_id: string
  vpn_profile_id: string
  source_ip: string
  vpn_ip: string
  status: 'active' | 'disconnected' | 'banned'
  connected_at: string
  disconnected_at?: string
  bytes_sent: number
  bytes_received: number
  duration_seconds: number
  username?: string
}

export interface ConnectionStats {
  total_connections: number
  active_connections: number
  total_users: number
  active_users: number
  total_bytes_sent: number
  total_bytes_received: number
}

// Firewall types
export interface FirewallRule {
  id: string
  name: string
  description?: string
  action: 'accept' | 'drop' | 'reject' | 'limit'
  protocol: 'tcp' | 'udp' | 'icmp' | 'all'
  source_network?: string
  destination_network?: string
  destination_port_range?: string
  priority: number
  is_active: boolean
  is_system_rule: boolean
  user_id?: string
  created_at: string
}

export interface FirewallRuleCreate {
  name: string
  description?: string
  action: 'accept' | 'drop' | 'reject' | 'limit'
  protocol?: 'tcp' | 'udp' | 'icmp' | 'all'
  source_network?: string
  destination_network?: string
  destination_port_range?: string
  priority?: number
  user_id?: string
}

// Dashboard types
export interface DashboardStats {
  total_users: number
  active_users: number
  total_connections: number
  active_connections: number
  total_bandwidth_today: number
  vpn_server_status: VPNServerStatus
}

// Common types
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface MessageResponse {
  message: string
}

export interface ErrorResponse {
  error: boolean
  message: string
  details?: unknown
}

// IPsec types
export interface IPsecConnection {
  id: string
  name: string
  description?: string
  left_ip: string
  left_subnet: string
  left_id: string
  right_ip: string
  right_ip_backup?: string
  right_subnet: string
  right_id: string
  auth_method: 'psk' | 'pubkey'
  ike_version: 'ikev1' | 'ikev2'
  ike_cipher: string
  ike_lifetime: string
  esp_cipher: string
  key_lifetime: string
  auto_start: boolean
  prefer_backup?: boolean
  dpd_action: 'restart' | 'clear' | 'hold' | 'none'
  status: 'active' | 'inactive' | 'connecting' | 'error'
  is_enabled: boolean
  last_status_check?: string
  last_error?: string
  created_at: string
  updated_at?: string
}

export interface IPsecConnectionCreate {
  name: string
  description?: string
  left_ip: string
  left_subnet: string
  left_id: string
  right_ip: string
  right_ip_backup?: string
  right_subnet: string
  right_id: string
  auth_method?: 'psk' | 'pubkey'
  psk?: string
  ike_version?: 'ikev1' | 'ikev2'
  ike_cipher?: string
  ike_lifetime?: string
  esp_cipher?: string
  key_lifetime?: string
  auto_start?: boolean
  dpd_action?: 'restart' | 'clear' | 'hold' | 'none'
  is_enabled?: boolean
}

export interface IPsecStatus {
  strongswan_running: boolean
  total_connections: number
  active_tunnels: number
  connections: Array<{
    name: string
    status: string
    ike_status?: string
    tunnel_status?: 'UP' | 'DOWN' | 'IKE_ONLY' | 'CONNECTING'
    has_child_sa?: boolean
    uptime?: string
    local_ts?: string
    remote_ts?: string
    bytes_in?: number
    bytes_out?: number
    rekey_time?: string
    error_hint?: string
    remote_host?: string | null
    active_paths?: number
    on_backup?: boolean | null
  }>
}

// Proxy Route types
export interface ProxyRoute {
  id: string
  name: string
  hostname: string
  backend_url: string
  path_prefix?: string
  strip_prefix: boolean
  ssl_mode: 'letsencrypt' | 'letsencrypt_dns' | 'custom' | 'none'
  force_https: boolean
  health_check_type: 'http' | 'tcp' | 'none'
  health_check_path?: string
  health_check_interval?: string
  pass_host_header: boolean
  custom_request_headers?: string
  custom_response_headers?: string
  rate_limit_average?: number
  rate_limit_burst?: number
  status: 'active' | 'inactive' | 'error' | 'pending'
  is_enabled: boolean
  last_health_check?: string
  last_health_status?: boolean
  last_error?: string
  ssl_certificate_expiry?: string
  ssl_certificate_issuer?: string
  created_at: string
  updated_at?: string
  created_by_id?: string
}

export interface CertificateInfo {
  domain: string
  sans: string[]
  issuer?: string
  not_before?: string
  not_after?: string
  days_remaining?: number
  status: 'valid' | 'expiring' | 'expired' | 'error'
  serial_number?: string
  fingerprint?: string
}

export interface CertificateListResponse {
  certificates: CertificateInfo[]
  acme_email?: string
  total: number
  valid: number
  expiring: number
  expired: number
}

// ACME DNS-01 Challenge types
export interface ACMEChallenge {
  id: string
  domain: string
  status: 'pending' | 'verified' | 'issued' | 'failed' | 'expired'
  txt_record_name?: string
  txt_record_value?: string
  proxy_route_id?: string
  error_message?: string
  expires_at?: string
  created_at: string
  updated_at: string
}

export interface ACMEVerifyResponse {
  id: string
  domain: string
  status: string
  success: boolean
  message: string
  error_message?: string
}

export interface ProxyRouteCreate {
  name: string
  hostname: string
  backend_url: string
  path_prefix?: string
  strip_prefix?: boolean
  ssl_mode?: 'letsencrypt' | 'letsencrypt_dns' | 'custom' | 'none'
  force_https?: boolean
  health_check_type?: 'http' | 'tcp' | 'none'
  health_check_path?: string
  health_check_interval?: string
  pass_host_header?: boolean
  custom_request_headers?: string
  custom_response_headers?: string
  rate_limit_average?: number
  rate_limit_burst?: number
  is_enabled?: boolean
}
