import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期将 /api 代理到本地 FastAPI，避免跨域
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
