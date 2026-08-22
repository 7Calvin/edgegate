import { test, expect } from '@playwright/test'

// Nome único por execução — regra do backend: letras, números, _ e -.
const username = `e2e_user_${Date.now()}`
const password = 'E2eTest12345!' // 12+ chars, maiúscula, minúscula, número, especial

test('criar usuário → aparece na lista → excluir', async ({ page }) => {
  await page.goto('/users')
  await expect(page.getByRole('heading', { name: 'Usuários' })).toBeVisible()

  // --- Criar ---
  await page.getByRole('button', { name: 'Adicionar Usuário' }).click()
  await expect(page.getByRole('heading', { name: 'Criar Novo Usuário' })).toBeVisible()
  await page.locator('#new-username').fill(username)
  await page.locator('#new-password').fill(password)
  await page.getByRole('button', { name: 'Criar', exact: true }).click()
  await expect(page.getByText('Usuário criado com sucesso')).toBeVisible()

  // --- Aparece na lista (busca isola a linha) ---
  await page.getByPlaceholder('Buscar usuários...').fill(username)
  await expect(page.getByText(username)).toBeVisible()

  // --- Excluir (confirmação exige digitar o nome) ---
  await page.getByRole('button', { name: 'Excluir usuário' }).click()
  await expect(page.getByRole('heading', { name: 'Excluir Usuário' })).toBeVisible()
  await page.locator('#confirm-username').fill(username)
  await page.getByRole('button', { name: 'Excluir Usuário' }).click()
  await expect(page.getByText('Usuário excluído com sucesso')).toBeVisible()

  // Sumiu da tabela.
  await expect(page.getByText(username)).toHaveCount(0)
})
