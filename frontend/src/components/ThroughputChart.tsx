import { useEffect, useMemo, useRef, useState } from 'react'
import { formatBytes } from '@/lib/utils'

export interface ThroughputPoint {
  timestamp: string
  bytes_sent: number // saída (server -> clients)
  bytes_received: number // entrada (clients -> server)
}

const PAD = { l: 8, r: 8, t: 14, b: 22 }
const H = 240

function hhmm(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function ThroughputChart({ points }: { points: ThroughputPoint[] }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(720)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => setW(Math.max(320, entries[0].contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const OUT = useMemo(() => points.map((p) => p.bytes_sent), [points])
  const IN = useMemo(() => points.map((p) => p.bytes_received), [points])
  const HOURS = useMemo(() => points.map((p) => hhmm(p.timestamp)), [points])

  const { outLine, outArea, inLine, xs, max, labelIdx } = useMemo(() => {
    const n = OUT.length
    if (n < 2) return { outLine: '', outArea: '', inLine: '', xs: [] as number[], max: 1, labelIdx: [] as number[] }
    const max = Math.max(...OUT, ...IN, 1) * 1.15
    const innerW = w - PAD.l - PAD.r
    const innerH = H - PAD.t - PAD.b
    const xs = OUT.map((_, i) => PAD.l + (innerW * i) / (n - 1))
    const y = (v: number) => PAD.t + innerH - (innerH * v) / max
    const line = (arr: number[]) => arr.map((v, i) => `${i === 0 ? 'M' : 'L'}${xs[i].toFixed(1)},${y(v).toFixed(1)}`).join(' ')
    const outLine = line(OUT)
    const inLine = line(IN)
    const outArea = `${outLine} L${xs[n - 1].toFixed(1)},${(PAD.t + innerH).toFixed(1)} L${xs[0].toFixed(1)},${(PAD.t + innerH).toFixed(1)} Z`
    // Show at most ~7 evenly-spaced x labels to avoid crowding.
    const step = Math.max(1, Math.ceil(n / 7))
    const labelIdx = OUT.map((_, i) => i).filter((i) => i % step === 0)
    return { outLine, outArea, inLine, xs, max, labelIdx }
  }, [w, OUT, IN])

  const y = (v: number) => PAD.t + (H - PAD.t - PAD.b) - ((H - PAD.t - PAD.b) * v) / max

  // Not enough samples yet — the background sampler needs at least two points
  // to compute a throughput interval.
  if (OUT.length < 2) {
    return (
      <div ref={wrapRef} className="w-full">
        <div className="flex items-center justify-center text-center text-sm text-muted-foreground" style={{ height: H }}>
          Coletando dados de throughput… o gráfico aparece após as primeiras amostras.
        </div>
      </div>
    )
  }

  return (
    <div ref={wrapRef} className="w-full">
      <svg
        width={w}
        height={H}
        className="block"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
          const x = e.clientX - rect.left
          let best = 0
          let bd = Infinity
          xs.forEach((xx, i) => { const d = Math.abs(xx - x); if (d < bd) { bd = d; best = i } })
          setHover(best)
        }}
      >
        <defs>
          <linearGradient id="egOut" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(188 84% 53%)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="hsl(188 84% 53%)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* gridlines */}
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={PAD.l} x2={w - PAD.r} y1={y(max * f)} y2={y(max * f)} stroke="hsl(210 45% 16%)" strokeWidth="1" strokeDasharray="2 4" />
        ))}

        {/* area + lines */}
        <path d={outArea} fill="url(#egOut)" />
        <path d={outLine} fill="none" stroke="hsl(188 84% 53%)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <path d={inLine} fill="none" stroke="hsl(255 100% 68%)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* x labels */}
        {labelIdx.map((i) => (
          <text key={i} x={xs[i]} y={H - 6} textAnchor="middle" className="fill-muted-foreground" style={{ fontSize: 10 }}>{HOURS[i]}</text>
        ))}

        {/* hover */}
        {hover !== null && (
          <g>
            <line x1={xs[hover]} x2={xs[hover]} y1={PAD.t} y2={H - PAD.b} stroke="hsl(210 45% 24%)" strokeWidth="1" />
            <circle cx={xs[hover]} cy={y(OUT[hover])} r="3.5" fill="hsl(188 84% 53%)" stroke="hsl(218 42% 9%)" strokeWidth="2" />
            <circle cx={xs[hover]} cy={y(IN[hover])} r="3.5" fill="hsl(255 100% 68%)" stroke="hsl(218 42% 9%)" strokeWidth="2" />
          </g>
        )}
      </svg>

      {/* tooltip */}
      {hover !== null && (
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="text-muted-foreground">{HOURS[hover]}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: 'hsl(188 84% 53%)' }} /><span className="text-muted-foreground">saída</span> <span className="font-medium text-foreground">{formatBytes(OUT[hover])}</span></span>
          <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: 'hsl(255 100% 68%)' }} /><span className="text-muted-foreground">entrada</span> <span className="font-medium text-foreground">{formatBytes(IN[hover])}</span></span>
        </div>
      )}
    </div>
  )
}
