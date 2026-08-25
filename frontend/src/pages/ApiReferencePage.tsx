import { useEffect, useState } from 'react'
import { api } from '@/api/client'

/**
 * API reference — the curated OpenAPI page, served by the backend behind admin auth
 * (the public Swagger /docs is disabled in production).
 *
 * Rendering under the app's strict CSP (script-src 'self', no 'unsafe-inline';
 * frame-src falls back to 'self'):
 *  - We fetch the HTML with the Bearer token and render it via srcDoc — a srcdoc iframe
 *    loads under frame-src 'self' (a blob: URL would be blocked).
 *  - The page's script is served as a SAME-ORIGIN external asset
 *    (/api/v1/system/api-reference.js), which script-src 'self' allows — inline scripts
 *    in the iframe would be blocked. That external <script src> is baked into the HTML.
 */
export default function ApiReferencePage() {
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .get('/system/api-reference', { responseType: 'text' })
      .then((r) => {
        if (alive) setHtml(r.data as string)
      })
      .catch(() => {
        if (alive) setError('Não foi possível carregar a referência da API.')
      })
    return () => {
      alive = false
    }
  }, [])

  if (error) {
    return <div className="p-6 text-sm text-muted-foreground">{error}</div>
  }

  if (html === null) {
    return (
      <div className="flex h-full min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary" />
      </div>
    )
  }

  return (
    <iframe
      title="Referência da API"
      srcDoc={html}
      className="w-full border-0"
      style={{ height: 'calc(100vh - 4rem)' }}
    />
  )
}
