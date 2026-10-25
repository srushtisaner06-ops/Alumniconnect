import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,            // listen on all interfaces so a phone / tunnel can reach it
    allowedHosts: true,    // accept tunnel hostnames (cloudflared, ngrok, ...)
    proxy: { '/api': 'http://localhost:8000' },
  },
  preview: { host: true, allowedHosts: true },
})
