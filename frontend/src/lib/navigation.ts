import {
  LayoutDashboard,
  Users,
  Shield,
  Lock,
  Globe,
  Network,
  Activity,
  ScrollText,
  Settings,
  Server,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  name: string
  href: string
  icon: LucideIcon
  adminOnly: boolean
  keywords?: string
  // Searchable in the command palette but NOT shown in the sidebar. Used for
  // deep-links into a page's sub-section (e.g. a Settings tab).
  hidden?: boolean
}

export interface NavGroup {
  // Section header shown above the group (FortiOS-style). Empty string => the
  // items render at the top level with no header (e.g. Dashboard).
  label: string
  // Glyph used to represent the whole group in the collapsed rail.
  icon?: LucideIcon
  items: NavItem[]
}

// Sidebar is organised by functional domain, mirroring the FortiOS console:
// a couple of standalone entries plus collapsible sections.
export const navGroups: NavGroup[] = [
  {
    label: '',
    items: [
      { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard, adminOnly: false, keywords: 'inicio home visao geral painel' },
    ],
  },
  {
    label: 'VPNs',
    icon: Shield,
    items: [
      { name: 'OpenVPN', href: '/vpn', icon: Shield, adminOnly: false, keywords: 'vpn servidor tunel perfil ovpn openvpn' },
      { name: 'IPsec', href: '/ipsec', icon: Lock, adminOnly: true, keywords: 'site to site tunel ike ipsec strongswan' },
    ],
  },
  {
    label: 'Rede',
    icon: Network,
    items: [
      { name: 'Firewall', href: '/firewall', icon: Network, adminOnly: true, keywords: 'regras rules rede interna firewall nat' },
      { name: 'Proxy Reverso', href: '/proxy', icon: Globe, adminOnly: true, keywords: 'reverse proxy traefik dominio certificado' },
    ],
  },
  {
    label: 'Acesso',
    icon: Users,
    items: [
      { name: 'Usuários', href: '/users', icon: Users, adminOnly: true, keywords: 'users contas acessos active directory ad' },
      { name: 'Conexões', href: '/connections', icon: Activity, adminOnly: true, keywords: 'connections clientes sessoes ativas' },
    ],
  },
  {
    label: 'Sistema',
    icon: Settings,
    items: [
      { name: 'Auditoria', href: '/audit', icon: ScrollText, adminOnly: true, keywords: 'audit logs eventos historico login' },
      { name: 'Configurações', href: '/settings', icon: Settings, adminOnly: false, keywords: 'settings conta senha mfa dominio ldap ad active directory autenticacao' },
    ],
  },
]

// Palette-only deep-links: searchable in ⌘K, never rendered in the sidebar.
const hiddenItems: NavItem[] = [
  { name: 'Autenticação AD (LDAP)', href: '/settings?tab=auth', icon: Network, adminOnly: true, hidden: true, keywords: 'ldap active directory ad autenticacao sincronizacao grupo vpn ntlm' },
  { name: 'Atualizações do sistema', href: '/settings?tab=sistema', icon: Server, adminOnly: true, hidden: true, keywords: 'update atualizacao versao release sistema deploy' },
]

// Flat list consumed by the command palette (unchanged API).
export const navigation: NavItem[] = [
  ...navGroups.flatMap((g) => g.items),
  ...hiddenItems,
]
