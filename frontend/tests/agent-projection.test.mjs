import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const server = await createServer({
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true },
  appType: 'custom',
})
after(() => server.close())

const { conversationProjectionFromEvents } = await server.ssrLoadModule(
  '/src/lib/agent-projection.ts',
)

test('uses only the latest user turn explicit ContextBundle refs', () => {
  const projection = conversationProjectionFromEvents([
    {
      type: 'user_msg',
      details: { context_bundles: [{ refs: [{ kind: 'node', ref_id: 'old' }] }] },
    },
    { type: 'agent_text', text: 'old answer' },
    {
      type: 'user_msg',
      details: {
        context_bundles: [{
          refs: [
            { kind: 'node', ref_id: 'n1' },
            { kind: 'edge', ref_id: 'e1' },
            { kind: 'node', ref_id: 'n1' },
          ],
        }],
      },
    },
    { type: 'status', status: 'running' },
    { type: 'agent_text', text: 'new answer' },
  ])

  assert.deepEqual(projection, {
    refs: [
      { kind: 'node', ref_id: 'n1' },
      { kind: 'edge', ref_id: 'e1' },
    ],
    text: 'new answer',
  })
})

test('does not infer projection targets from prose or selection-like details', () => {
  const projection = conversationProjectionFromEvents([
    { type: 'user_msg', text: 'look at node n1' },
    { type: 'agent_text', text: 'I think n1 is suspicious' },
  ])
  assert.deepEqual(projection, { refs: [], text: null })
})

test('ignores malformed context refs', () => {
  const projection = conversationProjectionFromEvents([
    {
      type: 'user_msg',
      details: {
        context_bundles: [{
          refs: [
            { kind: 'node', ref_id: '' },
            { kind: 'file', ref_id: 'x' },
            { kind: 'port', ref_id: 'p1' },
          ],
        }],
      },
    },
  ])
  assert.deepEqual(projection, {
    refs: [{ kind: 'port', ref_id: 'p1' }],
    text: null,
  })
})

test('a newer turn without explicit refs clears the previous graph projection', () => {
  const projection = conversationProjectionFromEvents([
    {
      type: 'user_msg',
      details: { context_bundles: [{ refs: [{ kind: 'node', ref_id: 'n1' }] }] },
    },
    { type: 'agent_text', text: 'about n1' },
    { type: 'user_msg', text: 'now answer generally' },
    { type: 'agent_text', text: 'general answer' },
  ])
  assert.deepEqual(projection, { refs: [], text: null })
})
