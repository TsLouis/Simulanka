import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/graph': 'http://127.0.0.1:8765',
      '/events': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        // SSE: keep the upstream connection open and don't buffer.
        ws: false,
      },
    },
  },
})
