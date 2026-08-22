import { test, expect } from '@playwright/test'
import { login, ADMIN_USER, ADMIN_PASS } from './helpers'

// Testes de login rodam SEM sessão salva (contexto limpo), pra exercitar o
// fluxo de autenticação de verdade.
test.use({ storageState: { cookies: [], origins: [] } })

test('login válido leva ao dashboard', async ({ page }) => {
  await login(page, ADMIN_USER, ADMIN_PASS)
  await expect(page.getByText('Dashboard', { exact: false }).first()).toBeVisible()
})

test('login inválido mostra erro e permanece no /login', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Usuário').fill('nao_existe')
  await page.getByLabel('Senha').fill('senhaErrada123!')
  await page.getByRole('button', { name: 'Entrar' }).click()

  // Toast de falha + não navegou pro dashboard.
  await expect(page.getByText('Login failed')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})
