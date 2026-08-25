import { useEffect, useState } from 'react'
import { api } from '@/api/client'

/**
 * API reference — the curated, self-contained OpenAPI page, served by the backend
 * behind authentication (the public Swagger /docs is disabled in production).
 *
 * Why fetch-and-iframe instead of a plain link: the API authenticates with a Bearer
 * token, and browsers don't send the Authorization header on plain navigation — so we
 * fetch the HTML through the axios client (which injects the token) and render it in an
 * iframe. We load it via a Blob URL (not srcDoc): the page is ~230KB and its <script>
 * lives at the end, and a srcDoc attribute that large can be truncated by the browser,
 * dropping the JS (search + tabs stop working). A blob: URL loads the whole document
 * reliably and runs its scripts. Public/unauthenticated requests get 401/403.
 */
export default function ApiReferencePage() {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    let url: string | null = null
    api
      .get('/system/api-reference', { responseType: 'text' })
      .then((r) => {
        if (!alive) return
        const blob = new Blob([r.data as string], { type: 'text/html' })
        url = URL.createObjectURL(blob)
        setSrc(url)
      })
      .catch(() => {
        if (alive) setError('Não foi possível carregar a referência da API.')
      })
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [])

  if (error) {
    return <div className="p-6 text-sm text-muted-foreground">{error}</div>
  }

  if (!src) {
    return (
      <div className="flex h-full min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary" />
      </div>
    )
  }

  return (
    <iframe
      title="Referência da API"
      src={src}
      className="w-full border-0"
      style={{ height: 'calc(100vh - 4rem)' }}
    />
  )
}
