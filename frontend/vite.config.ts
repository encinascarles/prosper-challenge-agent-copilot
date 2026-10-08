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
    // tools/wt/dev serves this over Tailscale HTTPS as <machine>.<tailnet>.ts.net:
    // HTTPS because browsers only give the microphone to a secure origin.
    allowedHosts: ['.ts.net'],
    // BACKEND_PORT lets each worktree run its own backend (tools/wt/dev).
    // /client, /start and /sessions are Pipecat's prebuilt test client and its
    // signalling, so it also works from the same origin.
    proxy: Object.fromEntries(
      ['/api', '/client', '/start', '/sessions'].map((path) => [
        path,
        `http://localhost:${process.env.BACKEND_PORT ?? 7860}`,
      ]),
    ),
  },
})
