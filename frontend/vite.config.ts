import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxy =
    env.VITE_DEV_API_PROXY || process.env.VITE_DEV_API_PROXY || 'http://localhost:5002'

  return {
  plugins: [react()],
  // Using custom domain, so root path for all modes
  base: '/',
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: apiProxy,
        changeOrigin: true,
        timeout: 300000,
        proxyTimeout: 300000,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
  },
}})

