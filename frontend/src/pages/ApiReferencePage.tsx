import { useEffect, useState } from 'react'
import { api } from '@/api/client'

/**
 * API reference — the curated, self-contained OpenAPI page, served by the backend
 * behind authentication (the public Swagger /docs is disabled in production).
 *
 * Why fetch-and-iframe instead of a plain link: the API authenticates with a Bearer
 * token, and browsers don't send the Authorization header on plain navigation — so we
 * fetch the HTML through the axios client (which injects the token) and render it in a
 * sandboxed iframe via srcDoc. Public/unauthenticated requests get 401.
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
