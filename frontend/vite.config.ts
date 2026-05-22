import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/graph': 'http://127.0.0.1:8765',
      // POST creates a user-drawn edge, DELETE /edge/{id} removes one (§13.5.2).
      '/edge': 'http://127.0.0.1:8765',
      // GET loads persisted layout, POST /ui/positions/{rootKey} saves drag
      // deltas. Without this rule dev-mode position persistence silently 404s
      // (the request hits the Vite dev server, not the backend).
      '/ui': 'http://127.0.0.1:8765',
      '/events': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        // SSE: keep the upstream connection open and don't buffer.
        ws: false,
      },
    },
  },
})
