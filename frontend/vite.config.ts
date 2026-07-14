import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/graph': 'http://127.0.0.1:8765',
      // POST creates a user-drawn edge, DELETE /edge/{id} removes one
      // (§13.5.2); /edge/{id}/verdict|accept|discuss are the §13.6 human ops.
      '/edge': 'http://127.0.0.1:8765',
      // §13.6 disagreement set. Every backend route MUST be listed here, or
      // dev-mode requests hit the Vite server and 404 (the /ui lesson).
      '/disagreements': 'http://127.0.0.1:8765',
      // §13.6 discussion session: /discussion/start|message + GET /discussion.
      // Prefix-matched, so all three ride this one rule (the /ui lesson again).
      '/discussion': 'http://127.0.0.1:8765',
      // S4 file viewer: GET /file/content?node=|path= reads registered file
      // nodes (markdown drawer, deep-link 出处, run logs).
      '/file': 'http://127.0.0.1:8765',
      // Canvas authoring: POST /node adds a node from the add-node menu,
      // POST /node/{id}/rename renames. (/ui/templates rides the /ui rule.)
      // Regex, NOT the usual prefix key: a bare '/node' prefix swallows
      // /node_modules/** and breaks every dev-mode module load (2026-07-12
      // 实测翻车). Proxy keys starting with ^ are treated as regex.
      '^/node(/|$)': 'http://127.0.0.1:8765',
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
