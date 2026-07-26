import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
// import vueDevTools from 'vite-plugin-vue-devtools'

const backendOrigin = process.env.VITE_BACKEND_ORIGIN ?? 'http://127.0.0.1:13140'

// https://vite.dev/config/
export default defineConfig({
  build: {
    outDir: '../yier_web/static',
    emptyOutDir: true,
  },
  plugins: [
    vue(),
    // vueDevTools(),
    tailwindcss(),
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    hmr: {
      // The HTML is served through the backend dev proxy on :13140, but the
      // Vite WebSocket still needs to connect to the real dev server.
      clientPort: 5173,
    },
    proxy: {
      '/api': {
        target: backendOrigin,
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
