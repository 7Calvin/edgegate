import { test as setup } from '@playwright/test'
import { login } from './helpers'

const AUTH_FILE = 'e2e/.auth/admin.json'

/**
 * Loga como admin UMA vez e persiste a sessão (o token fica no localStorage,
 * chave `auth-storage` do zustand). Os testes autenticados reusam esse estado
 * em vez de logar de novo a cada teste.
 */
setup('autentica como admin', async ({ page }) => {
  await login(page)
  await page.context().storageState({ path: AUTH_FILE })
})
