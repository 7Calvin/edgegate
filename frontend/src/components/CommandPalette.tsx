import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { navigation } from '@/lib/navigation'
import { cn } from '@/lib/utils'
import { Search, CornerDownLeft } from 'lucide-react'

/**
 * ⌘K / Ctrl+K command palette. Fuzzy-ish filter over the navigation
 * destinations; Enter or click to go. Kept dependency-free on purpose.
 */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const items = useMemo(() => {
    const visible = navigation.filter((i) => !i.adminOnly || user?.is_admin)
    const q = query.trim().toLowerCase()
    if (!q) return visible
    return visible.filter(
      (i) => i.name.toLowerCase().includes(q) || (i.keywords ?? '').includes(q)
    )
  }, [query, user?.is_admin])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      // focus after paint
      const t = setTimeout(() => inputRef.current?.focus(), 20)
      return () => clearTimeout(t)
    }
  }, [open])

  useEffect(() => {
    setActive(0)
  }, [query])

  if (!open) return null

  const go = (href: string) => {
    onOpenChange(false)
    navigate(href)
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 backdrop-blur-sm pt-[12vh] px-4"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-popover shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          else if (e.key === 'Enter') { e.preventDefault(); if (items[active]) go(items[active].href) }
          else if (e.key === 'Escape') { onOpenChange(false) }
        }}
      >
        <div className="flex items-center gap-3 border-b border-border px-4">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar ou executar comando"
            className="w-full bg-transparent py-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          <kbd className="rounded border border-border bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">Nada encontrado</p>
          ) : (
            items.map((item, i) => (
              <button
                key={item.href}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(item.href)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors',
                  i === active ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-accent/50'
                )}
              >
                <item.icon className={cn('h-4 w-4', i === active ? 'text-primary' : '')} />
                <span className="flex-1 text-left">{item.name}</span>
                {i === active && <CornerDownLeft className="h-3.5 w-3.5 text-muted-foreground" />}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
