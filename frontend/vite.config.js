import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,            // listen on all interfaces so a phone / tunnel can reach it
    allowedHosts: true,    // accept tunnel hostnames (cloudflared, ngrok, ...)
    // xfwd adds X-Forwarded-For; set TRUST_PROXY_HOPS in backend/.env (ngrok -> Vite -> API = 2) so rate limits see real visitors
    proxy: { '/api': { target: 'http://localhost:8000', xfwd: true } },
  },
  preview: { host: true, allowedHosts: true },
})
