import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // Dev proxy. Defaults to a local backend; set VITE_DEV_API to point the
      // preview at a live server, e.g. VITE_DEV_API=https://vpn.example.com
      '/api': {
        target: process.env.VITE_DEV_API || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/health': {
        target: process.env.VITE_DEV_API || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
