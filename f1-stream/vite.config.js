import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Allowlist tunnel domains used to expose the dev server to Browser Use Cloud.
    // Explicit patterns rather than `true` to avoid DNS-rebinding exposure (CVE-2025-24010).
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app', '.ngrok.io'],
  },
})
