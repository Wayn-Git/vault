import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import http from 'node:http'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        // SSE through the proxy hangs when http-proxy reuses a keep-alive
        // socket whose upstream side the backend already closed. Fresh
        // connection per request removes the race.
        agent: new http.Agent({ keepAlive: false }),
        configure: (proxy) => {
          proxy.on('error', (err) => {
            console.error('[proxy]', err.message)
          })
        },
      },
    },
  },
})