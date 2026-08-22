import { cn } from '@/lib/utils'

/** EdgeGate shield mark. Cyan shield on a rounded dark tile. */
export function LogoMark({ className, size = 32 }: { className?: string; size?: number }) {
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-xl bg-[#06090f] ring-1 ring-primary/30 shrink-0',
        className
      )}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 100 100"
        width={size * 0.6}
        height={size * 0.6}
        aria-hidden
      >
        <path
          d="M50 24 l20 7 v16 c0 13 -10 21 -20 24 c-10 -3 -20 -11 -20 -24 V31 Z"
          fill="none"
          stroke="hsl(var(--primary))"
          strokeWidth={6}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
    </span>
  )
}

export function Logo({ collapsed = false, size = 34 }: { collapsed?: boolean; size?: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark size={size} />
      {!collapsed && (
        <span className="text-lg font-bold tracking-tight text-foreground">
          Edge<span className="text-primary">Gate</span>
        </span>
      )}
    </div>
  )
}
