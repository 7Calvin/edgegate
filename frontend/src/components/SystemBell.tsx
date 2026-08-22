import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, ChevronRight } from 'lucide-react'
import type { SystemAlert } from '@/hooks/useSystemStatus'
import { cn } from '@/lib/utils'

export function SystemBell({ alerts }: { alerts: SystemAlert[] }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const count = alerts.length
  const hasDown = alerts.some((a) => a.level === 'down')

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative text-muted-foreground hover:text-foreground"
        title="Alertas"
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span
            className={cn(
              'absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold',
              hasDown ? 'bg-destructive text-destructive-foreground' : 'bg-primary text-primary-foreground'
            )}
          >
            {count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-xl border border-border bg-popover shadow-xl">
            <div className="border-b border-border px-3 py-2 text-sm font-medium text-foreground">Alertas</div>
            {count === 0 ? (
              <p className="px-3 py-5 text-center text-sm text-muted-foreground">Nenhum alerta — tudo em ordem.</p>
            ) : (
              <ul className="max-h-72 overflow-y-auto py-1">
                {alerts.map((a, i) => {
                  const dot = (
                    <span
                      className={cn(
                        'mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full',
                        a.level === 'down' ? 'bg-destructive' : a.level === 'warn' ? 'bg-warning' : 'bg-primary'
                      )}
                    />
                  )
                  return a.href ? (
                    <li key={i}>
                      <button
                        onClick={() => { setOpen(false); navigate(a.href!) }}
                        className="group flex w-full items-start gap-2.5 px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent/40"
                      >
                        {dot}
                        <span className="flex-1 text-foreground">{a.text}</span>
                        <ChevronRight className="mt-0.5 h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </button>
                    </li>
                  ) : (
                    <li key={i} className="flex items-start gap-2.5 px-3 py-2.5 text-sm">
                      {dot}
                      <span className="text-foreground">{a.text}</span>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
