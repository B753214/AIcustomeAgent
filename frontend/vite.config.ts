import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 生产环境由 FastAPI 挂在 /console；开发态仍用 Vite :5173
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/console/' : '/',
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/sessions': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
}))
