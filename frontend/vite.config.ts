import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * The browser only ever calls same-origin `/api/...`. Vite proxies that to the
 * Express API. This matters in hosted preview environments: the user's browser is
 * not the sandbox, so the frontend must never call localhost directly.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // Allow any Host header so proxied preview domains work.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:4000',
        changeOrigin: true,
      },
    },
  },
  preview: { host: '0.0.0.0', port: 5173, allowedHosts: true },
});
