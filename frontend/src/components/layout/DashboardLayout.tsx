import { Outlet, Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { navGroups, type NavItem } from '@/lib/navigation'
import { Logo, LogoMark } from '@/components/Logo'
import { CommandPalette } from '@/components/CommandPalette'
import { SystemBell } from '@/components/SystemBell'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { LogOut, Menu, X, Search, PanelLeftClose, PanelLeft, ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { systemApi } from '@/api/client'

export default function DashboardLayout() {
  const { user, logout } = useAuthStore()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('eg.rail') === '1')
  const [cmdkOpen, setCmdkOpen] = useState(false)
  const [version, setVersion] = useState<string | null>(null)
  const { alerts, isAdmin } = useSystemStatus()

  useEffect(() => {
    systemApi.version().then((res) => setVersion(res.data?.current ?? null)).catch(() => setVersion(null))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCmdkOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      localStorage.setItem('eg.rail', c ? '0' : '1')
      return !c
    })
  }

  // Filter each group's items by admin visibility, drop empty groups.
  const visibleGroups = navGroups
    .map((g) => ({ ...g, items: g.items.filter((i) => (!i.adminOnly || user?.is_admin) && !i.hidden) }))
    .filter((g) => g.items.length > 0)
  // Collapsed rail shows every leaf as a flat icon list (groups flatten).
  const visibleLeaves = visibleGroups.flatMap((g) => g.items)

  const isActive = (href: string) => location.pathname === href || location.pathname.startsWith(href + '/')

  // Collapsible sections: collapsed by default; the section holding the current
  // route auto-expands. An explicit user toggle overrides both.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})
  const isGroupActive = (items: NavItem[]) => items.some((i) => isActive(i.href))
  const isGroupOpen = (g: { label: string; items: NavItem[] }) => openGroups[g.label] ?? isGroupActive(g.items)
  const toggleGroup = (g: { label: string; items: NavItem[] }) => setOpenGroups((s) => ({ ...s, [g.label]: !isGroupOpen(g) }))

  const renderLink = (item: NavItem, opts?: { indented?: boolean }) => {
    const active = isActive(item.href)
    return (
      <Link
        key={item.href}
        to={item.href}
        onClick={() => setMobileOpen(false)}
        title={collapsed ? item.name : undefined}
        className={cn(
          'group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
          collapsed && 'justify-center px-0',
          opts?.indented && !collapsed && 'pl-9',
          active ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground'
        )}
      >
        {active && <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-primary" />}
        <item.icon className={cn('h-5 w-5 shrink-0', active && 'text-primary')} />
        {!collapsed && <span>{item.name}</span>}
      </Link>
    )
  }

  const domain = typeof window !== 'undefined' ? window.location.hostname : ''

  const railWidth = collapsed ? 'lg:w-[72px]' : 'lg:w-60'
  const contentPad = collapsed ? 'lg:pl-[72px]' : 'lg:pl-60'

  return (
    <div className="min-h-screen bg-background">
      <CommandPalette open={cmdkOpen} onOpenChange={setCmdkOpen} />

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-border bg-[#0a0f18] transition-all duration-200 ease-in-out',
          railWidth,
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        )}
      >
        {/* Brand */}
        <div className={cn('flex h-16 items-center border-b border-border', collapsed ? 'justify-center px-2' : 'justify-between px-4')}>
          <Link to="/dashboard" onClick={() => setMobileOpen(false)}>
            <Logo collapsed={collapsed} />
          </Link>
          <button
            className="hidden lg:inline-flex text-muted-foreground hover:text-foreground"
            onClick={toggleCollapsed}
            title={collapsed ? 'Expandir' : 'Recolher'}
          >
            {collapsed ? null : <PanelLeftClose className="h-4 w-4" />}
          </button>
          <button className="lg:hidden text-muted-foreground hover:text-foreground" onClick={() => setMobileOpen(false)}>
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {collapsed && (
            <button
              className="mb-2 hidden lg:flex w-full items-center justify-center rounded-lg py-2 text-muted-foreground hover:bg-accent/40 hover:text-foreground"
              onClick={toggleCollapsed}
              title="Expandir"
            >
              <PanelLeft className="h-5 w-5" />
            </button>
          )}
          {collapsed
            ? visibleLeaves.map((item) => renderLink(item))
            : visibleGroups.map((group) => {
                if (!group.label) return group.items.map((item) => renderLink(item))
                const open = isGroupOpen(group)
                return (
                  <div key={group.label} className="pt-3 first:pt-0">
                    <button
                      onClick={() => toggleGroup(group)}
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60 transition-colors hover:text-foreground"
                    >
                      {group.icon && <group.icon className="h-3.5 w-3.5 shrink-0" />}
                      <span className="flex-1 text-left">{group.label}</span>
                      <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', !open && '-rotate-90')} />
                    </button>
                    {open && <div className="mt-1 space-y-1">{group.items.map((item) => renderLink(item, { indented: true }))}</div>}
                  </div>
                )
              })}
        </nav>

      </aside>

      {/* Main */}
      <div className={cn('transition-all duration-200', contentPad)}>
        {/* Topbar */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur lg:px-6">
          <button className="lg:hidden text-muted-foreground hover:text-foreground" onClick={() => setMobileOpen(true)}>
            <Menu className="h-5 w-5" />
          </button>

          {/* Domain / subtitle */}
          <div className="hidden min-w-0 sm:flex items-center gap-2.5">
            <LogoMark size={28} className="lg:hidden" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">{domain || 'EdgeGate'}</p>
              <p className="truncate text-xs text-muted-foreground">
                painel de gerenciamento{version ? ` · v${version}` : ''}
              </p>
            </div>
          </div>

          {/* Command palette trigger */}
          <button
            onClick={() => setCmdkOpen(true)}
            className="mx-auto hidden w-full max-w-md items-center gap-2 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-sm text-muted-foreground transition-colors hover:border-primary/40 md:flex"
          >
            <Search className="h-4 w-4" />
            <span className="flex-1 text-left">Buscar ou executar comando</span>
            <kbd className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px]">⌘K</kbd>
          </button>

          <div className="ml-auto flex items-center gap-2 md:ml-0">
            <button
              onClick={() => setCmdkOpen(true)}
              className="md:hidden text-muted-foreground hover:text-foreground"
              title="Buscar (⌘K)"
            >
              <Search className="h-5 w-5" />
            </button>
            {isAdmin && <SystemBell alerts={alerts} />}
            <div className="ml-1 flex items-center gap-2 border-l border-border pl-3">
              <div className="hidden text-right leading-tight sm:block">
                <p className="text-sm font-medium text-foreground">{user?.username}</p>
                <p className="text-xs text-muted-foreground">{user?.is_admin ? 'Administrador' : 'Usuário'}</p>
              </div>
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary ring-1 ring-primary/30">
                {user?.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <button onClick={logout} title="Sair" className="text-muted-foreground hover:text-destructive">
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        </header>

        <main className="p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
