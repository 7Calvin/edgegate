import { expect, type Page } from '@playwright/test'

export const ADMIN_USER = process.env.E2E_ADMIN_USER || 'admin'
export const ADMIN_PASS = process.env.E2E_ADMIN_PASS || 'Admin123!@#456'

/**
 * Faz login pela UI (form real) e espera cair no dashboard.
 * Usado pelo auth.setup.ts e pelo teste de login válido.
 */
export async function login(page: Page, user = ADMIN_USER, pass = ADMIN_PASS) {
  await page.goto('/login')
  await page.getByLabel('Usuário').fill(user)
  await page.getByLabel('Senha').fill(pass)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
}
