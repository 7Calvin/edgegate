import { defineConfig, devices } from '@playwright/test'

/**
 * Smoke E2E do EdgeGate — roda contra o STACK REAL (docker-compose).
 *
 * O frontend fala com a API em `/api/v1` (relativo) e quem roteia isso é o
 * Traefik, então o ponto de entrada é sempre o Traefik em https://localhost
 * (não a porta 8000 do backend nem o Vite dev). O cert é self-signed, por isso
 * `ignoreHTTPSErrors`.
 *
 * Antes de rodar, suba o stack:  docker-compose up -d
 * Depois:                        npm run test:e2e
 *
 * Dá pra apontar pra outro host/credenciais por env:
 *   E2E_BASE_URL   (default https://localhost)
 *   E2E_ADMIN_USER (default admin           — bate com o compose)
 *   E2E_ADMIN_PASS (default Admin123!@#456  — bate com o compose)
 */
const BASE_URL = process.env.E2E_BASE_URL || 'https://localhost'

export default defineConfig({
  testDir: './e2e',
  // Smoke fino: uma coisa de cada vez, falha na primeira quebra real.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true, // Traefik serve cert self-signed em https://localhost
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    // 1) Loga uma vez e salva a sessão em e2e/.auth/admin.json.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },

    // 2) Testes autenticados reaproveitam a sessão salva.
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: 'e2e/.auth/admin.json' },
      dependencies: ['setup'],
    },
  ],
})
