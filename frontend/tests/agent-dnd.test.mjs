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

const {
  AGENT_REF_MIME,
  hasAgentDragRef,
  readAgentDragRef,
  readAgentDragRefs,
  writeAgentDragRef,
  writeAgentDragRefs,
} = await server.ssrLoadModule('/src/lib/agent-dnd.ts')

class FakeTransfer {
  data = new Map()
  effectAllowed = 'none'
  dropEffect = 'none'

  get types() {
    return [...this.data.keys()]
  }

  setData(type, value) {
    this.data.set(type, String(value))
  }

  getData(type) {
    return this.data.get(type) ?? ''
  }
}

const eventWith = transfer => ({ dataTransfer: transfer })

test('writes and reads a typed node/edge/port reference without implicit context', () => {
  for (const kind of ['node', 'edge', 'port']) {
    const transfer = new FakeTransfer()
    const event = eventWith(transfer)
    writeAgentDragRef(event, { kind, ref_id: `${kind}-1`, label: `${kind} label` })

    assert.equal(transfer.effectAllowed, 'copy')
    assert.equal(hasAgentDragRef(event), true)
    assert.equal(transfer.getData('text/plain'), `${kind} label`)
    assert.deepEqual(readAgentDragRef(event), {
      kind,
      ref_id: `${kind}-1`,
      label: `${kind} label`,
    })
  }
})

test('a selected RefSet roundtrips as explicit context and deduplicates repeated refs', () => {
  const transfer = new FakeTransfer()
  const event = eventWith(transfer)
  writeAgentDragRefs(event, [
    { kind: 'node', ref_id: 'n1', label: 'experiment · E1' },
    { kind: 'node', ref_id: 'n2', label: 'evidence · V1' },
    { kind: 'node', ref_id: 'n1', label: 'duplicate label' },
  ])

  assert.equal(transfer.getData('text/plain'), '3 Simulanka objects')
  assert.deepEqual(readAgentDragRefs(event), [
    { kind: 'node', ref_id: 'n1', label: 'experiment · E1' },
    { kind: 'node', ref_id: 'n2', label: 'evidence · V1' },
  ])
})

test('ordinary text drags are not Agent context', () => {
  const transfer = new FakeTransfer()
  transfer.setData('text/plain', 'not a graph reference')
  const event = eventWith(transfer)

  assert.equal(hasAgentDragRef(event), false)
  assert.equal(readAgentDragRef(event), null)
  assert.deepEqual(readAgentDragRefs(event), [])
})

test('malformed or unsupported typed payload members are rejected', () => {
  for (const payload of [
    '{bad json',
    JSON.stringify({ kind: 'file', ref_id: 'x', label: 'x' }),
    JSON.stringify({ kind: 'node', ref_id: '', label: 'x' }),
    JSON.stringify({ kind: 'node', ref_id: 'n1', label: '' }),
  ]) {
    const transfer = new FakeTransfer()
    transfer.setData(AGENT_REF_MIME, payload)
    assert.equal(readAgentDragRef(eventWith(transfer)), null)
  }

  const mixed = new FakeTransfer()
  mixed.setData(AGENT_REF_MIME, JSON.stringify([
    { kind: 'node', ref_id: 'n1', label: 'valid' },
    { kind: 'file', ref_id: 'f1', label: 'invalid kind' },
    { kind: 'edge', ref_id: '', label: 'invalid id' },
  ]))
  assert.deepEqual(readAgentDragRefs(eventWith(mixed)), [
    { kind: 'node', ref_id: 'n1', label: 'valid' },
  ])
})
