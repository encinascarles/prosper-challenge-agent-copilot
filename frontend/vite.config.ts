import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    // One origin for the browser: API calls (and Pipecat's WebRTC signalling
    // at /api/offer) go to the Pipecat FastAPI server, so no CORS setup.
    proxy: {
      '/api': 'http://localhost:7860',
    },
  },
})
