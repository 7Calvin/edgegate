import { test, expect, type Page } from '@playwright/test'

// Telas de leitura pesada: só precisam renderizar sem estourar erro de JS e
// mostrar seu cabeçalho. É o "o app está de pé?" da UI.
const pages: Array<{ path: string; heading: string }> = [
  { path: '/firewall', heading: 'Firewall' },
  { path: '/connections', heading: 'Conexões' },
  { path: '/dashboard', heading: 'Dashboard' },
]

function trackErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  return errors
}

for (const { path, heading } of pages) {
  test(`${path} renderiza sem erro`, async ({ page }) => {
    const errors = trackErrors(page)
    await page.goto(path)
    // Rotas admin não devem redirecionar (logamos como admin).
    await expect(page).toHaveURL(new RegExp(path.replace('/', '\\/')))
    await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible()
    expect(errors, `erros de JS em ${path}:\n${errors.join('\n')}`).toEqual([])
  })
}
