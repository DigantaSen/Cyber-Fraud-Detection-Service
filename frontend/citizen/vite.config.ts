import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(() => {
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api/v1/auth': {
          target: 'http://localhost:8010',
          changeOrigin: true,
        },
        '/api': {
          target: 'http://localhost:8013',
          changeOrigin: true,
        }
      }
    }
  }
})
