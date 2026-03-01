import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@convex': path.resolve(__dirname, '../convex/_generated'),
    },
  server: {
    // Allowlist tunnel domains used to expose the dev server to Browser Use Cloud.
    // Explicit patterns rather than `true` to avoid DNS-rebinding exposure (CVE-2025-24010).
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app', '.ngrok.io'],
  },
})
