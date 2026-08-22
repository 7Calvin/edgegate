import { test, expect } from '@playwright/test'

// Deixamos `enabled` desligado de propósito: o round-trip prova que a config
// persiste sem alterar o fluxo de auth (contas locais seguem funcionando).
const server = 'e2e-dc.example.local'
const base = 'DC=e2e,DC=local'

test('configurar AD/LDAP salva e persiste após reload', async ({ page }) => {
  await page.goto('/settings?tab=auth')
  await expect(page.getByText('Autenticação Active Directory (LDAP)')).toBeVisible()

  await page.locator('#ldap-server').fill(server)
  await page.locator('#ldap-base').fill(base)
  await page.getByRole('button', { name: 'Salvar' }).click()
  await expect(page.getByText('Configuração do AD salva')).toBeVisible()

  // Recarrega e confirma que o servidor voltou hidratado do backend.
  await page.goto('/settings?tab=auth')
  await expect(page.locator('#ldap-server')).toHaveValue(server)
  await expect(page.locator('#ldap-base')).toHaveValue(base)
})
