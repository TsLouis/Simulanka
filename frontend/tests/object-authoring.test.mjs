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

const { createPort, updatePort, deletePort, objectAction, portAction } =
  await server.ssrLoadModule('/src/lib/object-authoring.ts')

const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
})

function mockFetch(expectedUrl, expectedMethod, payload) {
  globalThis.fetch = async (url, init = {}) => {
    assert.equal(url, expectedUrl)
    assert.equal(init.method, expectedMethod)
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}

test('createPort uses frozen node port endpoint', async () => {
  mockFetch('/node/nod_1/ports', 'POST', { port_id: 'prt_1', graph_version: 4 })
  const result = await createPort('nod_1', {
    name: 'x',
    direction: 'in',
    port_type: 'tensor',
  })
  assert.deepEqual(result, { port_id: 'prt_1', graph_version: 4 })
})

test('updatePort uses frozen port update endpoint', async () => {
  mockFetch('/port/prt_1/update', 'POST', { port_id: 'prt_1', graph_version: 5 })
  const result = await updatePort('prt_1', { name: 'renamed' })
  assert.deepEqual(result, { port_id: 'prt_1', graph_version: 5 })
})

test('deletePort uses frozen delete endpoint', async () => {
  mockFetch('/port/prt_1', 'DELETE', { deleted: ['prt_1'], graph_version: 6 })
  const result = await deletePort('prt_1')
  assert.deepEqual(result, { deleted: ['prt_1'], graph_version: 6 })
})

test('objectAction and portAction preserve server authority', () => {
  const affordances = [
    {
      id: 'port.update',
      label: 'Edit port',
      enabled: false,
      reason: 'Disconnect incident edges first',
      reason_code: 'state_locked',
      input_schema: {},
    },
  ]
  assert.equal(objectAction(affordances, 'port.update'), affordances[0])
  assert.equal(objectAction(affordances, 'port.delete'), null)
  const port = {
    id: 'prt_1',
    node_id: 'nod_1',
    name: 'x',
    side: 'in',
    port_type: 'tensor',
    attrs: {},
    capabilities: [],
    unknown_profile: false,
    affordances,
  }
  assert.equal(portAction(port, 'port.update'), affordances[0])
})

test('mutation errors surface server body', async () => {
  globalThis.fetch = async () => new Response('connected port', { status: 422 })
  await assert.rejects(
    () => updatePort('prt_1', { direction: 'out' }),
    /update port failed: 422 connected port/,
  )
})
