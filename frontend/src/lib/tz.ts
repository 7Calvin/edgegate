// Display timezone preference. Timestamps are stored in UTC on the backend and
// formatted client-side in the chosen zone. Empty string = use the browser zone.

const KEY = 'eg.tz'

export const TIMEZONES: { value: string; label: string }[] = [
  { value: '', label: 'Automático (navegador)' },
  { value: 'America/Sao_Paulo', label: 'Brasília (UTC−3)' },
  { value: 'America/Manaus', label: 'Manaus (UTC−4)' },
  { value: 'America/Rio_Branco', label: 'Rio Branco (UTC−5)' },
  { value: 'America/Noronha', label: 'Fernando de Noronha (UTC−2)' },
  { value: 'UTC', label: 'UTC' },
  { value: 'America/New_York', label: 'New York (UTC−5/−4)' },
  { value: 'Europe/Lisbon', label: 'Lisboa (UTC+0/+1)' },
]

export function getTimezone(): string {
  try {
    return localStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

export function setTimezone(tz: string) {
  try {
    if (tz) localStorage.setItem(KEY, tz)
    else localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

/** Format a UTC/ISO timestamp in the configured display timezone. */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  opts: { withSeconds?: boolean; dateOnly?: boolean } = {}
): string {
  if (value === null || value === undefined || value === '') return '—'
  const d = value instanceof Date ? value : new Date(value)
  if (isNaN(d.getTime())) return '—'
  const tz = getTimezone() || undefined
  const fmt: Intl.DateTimeFormatOptions = opts.dateOnly
    ? { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: tz }
    : {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
        ...(opts.withSeconds ? { second: '2-digit' } : {}),
        hour12: false, timeZone: tz,
      }
  return new Intl.DateTimeFormat('pt-BR', fmt).format(d)
}

/** Short label of the active timezone for display (e.g. "UTC−3"). */
export function activeTimezoneLabel(): string {
  const tz = getTimezone()
  return TIMEZONES.find((t) => t.value === tz)?.label ?? (tz || 'Automático (navegador)')
}
