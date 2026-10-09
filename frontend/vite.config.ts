import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 중 /api 요청은 FastAPI(8000)로 넘긴다
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
