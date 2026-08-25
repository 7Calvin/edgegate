// Turn an API/axios error into a human-friendly message for toasts.
//
// The backend wraps errors as:
//   - validation:  { error: true, message: "Validation error", details: [{ loc, msg }] }
//   - HTTP errors: { error: true, message: "..." }  or  { detail: "..." }
//   - some routes: { detail: { error, suggestion, error_type } }
// This extracts the most specific message available (field-level validation msgs
// first) so the user sees WHAT was wrong, not just "Erro desconhecido".

interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
}

interface ApiErrorData {
  message?: string
  detail?: string | { error?: string; suggestion?: string } | ValidationItem[]
  details?: ValidationItem[]
}

interface ApiErrorLike {
  response?: { data?: ApiErrorData }
  message?: string
}

function formatValidationItems(items: ValidationItem[]): string {
  return items
    .map((d) => {
      const field = Array.isArray(d.loc) && d.loc.length ? String(d.loc[d.loc.length - 1]) : ''
      // Pydantic v2 prefixes custom validator messages with "Value error, "
      const msg = (d.msg || '').replace(/^Value error,\s*/i, '')
      return field ? `${field}: ${msg}` : msg
    })
    .filter(Boolean)
    .join(' · ')
}

export function getApiErrorMessage(err: unknown, fallback = 'Erro desconhecido'): string {
  const e = err as ApiErrorLike
  const data = e?.response?.data

  if (data) {
    // Field-level validation errors (most specific)
    if (Array.isArray(data.details) && data.details.length) {
      const m = formatValidationItems(data.details)
      if (m) return m
    }
    if (Array.isArray(data.detail) && data.detail.length) {
      const m = formatValidationItems(data.detail as ValidationItem[])
      if (m) return m
    }
    // Structured detail with a friendly error + suggestion
    if (data.detail && typeof data.detail === 'object' && !Array.isArray(data.detail)) {
      const d = data.detail as { error?: string; suggestion?: string }
      if (d.error) return d.suggestion ? `${d.error} — ${d.suggestion}` : d.error
    }
    // Plain string detail
    if (typeof data.detail === 'string' && data.detail) return data.detail
    // Generic backend message (skip the useless "Validation error" wrapper if we got here)
    if (typeof data.message === 'string' && data.message && data.message !== 'Validation error') {
      return data.message
    }
  }

  if (typeof e?.message === 'string' && e.message) return e.message
  return fallback
}
