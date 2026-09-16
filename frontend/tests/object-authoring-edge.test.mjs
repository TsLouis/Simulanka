import assert from 'node:assert/strict'
import { after, afterEach, test } from 'node:test'
import { createServer } from 'vite'

const server = await createServer({
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true },
  appType: 'custom',
})
after(() => server.close())

const { disconnectEdge, edgeAction } = await server.ssrLoadModule('/src/lib/object-authoring.ts')
const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test('disconnectEdge reuses persisted edge DELETE endpoint', async () => {
  globalThis.fetch = async (url, init = {}) => {
    assert.equal(url, '/edge/edg_1')
    assert.equal(init.method, 'DELETE')
    return new Response('{}', { status: 200 })
  }
  await disconnectEdge('edg_1')
})

test('edgeAction projects server edge.delete affordance', () => {
  const action = {
    id: 'edge.delete',
    label: 'Disconnect',
    enabled: false,
    reason: 'Structural edge cannot be disconnected directly',
    reason_code: 'state_locked',
    input_schema: {},
  }
  const edge = {
    id: 'edg_1', type: 'contains', src: 'n1', dst: 'n2', src_port: null, dst_port: null,
    attrs: {}, capabilities: [], unknown_profile: false, affordances: [action],
  }
  assert.equal(edgeAction(edge, 'edge.delete'), action)
})
