import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
  preview: {
    port: 4173,
  },
  build: {
    // The WebGL runtime is isolated from the 20 kB application entry chunk.
    // Its minified size is expected because Three.js and drei ship together.
    chunkSizeWarningLimit: 950,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          const normalizedId = id.replaceAll('\\', '/')
          if (normalizedId.includes('@react-three')) return 'react-three'
          if (normalizedId.includes('/three/')) return 'three'
          if (normalizedId.includes('/react/') || normalizedId.includes('/react-dom/')) {
            return 'react'
          }
          return 'vendor'
        },
      },
    },
  },
})
