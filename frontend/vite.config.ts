import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxy =
    env.VITE_DEV_API_PROXY || process.env.VITE_DEV_API_PROXY || 'http://localhost:5002'
  const allowedHosts = (env.VITE_ALLOWED_HOSTS || process.env.VITE_ALLOWED_HOSTS || '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)

  return {
    plugins: [react()],
    base: '/',
    server: {
      host: '127.0.0.1',
      port: 3000,
      strictPort: false,
      allowedHosts: allowedHosts.length > 0 ? allowedHosts : ['signhousedemo.cynthai.com'],
      proxy: {
        '/api': {
          target: apiProxy,
          changeOrigin: true,
          timeout: 300000,
          proxyTimeout: 300000,
        },
        '/mcp': {
          target: apiProxy,
          changeOrigin: true,
          timeout: 300000,
          proxyTimeout: 300000,
          bypass(req) {
            const accept = String(req.headers?.accept ?? '')
            if (req.method === 'GET' && accept.includes('text/html')) {
              return '/index.html'
            }
          },
        },
      },
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: false,
    },
  }
})
