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
  draftFromPort,
  allowedPortTypes,
  validatePortDraft,
  updateRequestFromDraft,
} = await server.ssrLoadModule('/src/lib/port-authoring.ts')

const port = {
  id: 'prt_1',
  node_id: 'nod_1',
  name: 'image',
  side: 'in',
  port_type: 'tensor',
  attrs: {
    label: 'Image',
    shape: [1, 3, 224, 224],
    confidence: 'verified',
    source: 'importer',
  },
  capabilities: [],
  unknown_profile: false,
  affordances: [],
}

const descriptor = {
  port_types: ['any', 'tensor', 'scalar'],
}

test('draftFromPort exposes only bounded editable presentation fields', () => {
  assert.deepEqual(draftFromPort(port), {
    name: 'image',
    direction: 'in',
    portType: 'tensor',
    label: 'Image',
    shape: '1×3×224×224',
    confidence: 'verified',
  })
})

test('allowedPortTypes falls back safely before Registry descriptor loads', () => {
  assert.deepEqual(allowedPortTypes(null), ['any'])
  assert.deepEqual(allowedPortTypes(descriptor), ['any', 'tensor', 'scalar'])
})

test('validation rejects empty names, unknown types, and invalid shapes', () => {
  const base = draftFromPort(port)
  assert.equal(validatePortDraft({ ...base, name: '  ' }, descriptor).valid, false)
  assert.equal(validatePortDraft({ ...base, portType: 'video' }, descriptor).valid, false)
  assert.equal(validatePortDraft({ ...base, shape: '1×oops×3' }, descriptor).valid, false)
  assert.equal(validatePortDraft({ ...base, shape: '1 3 224 224' }, descriptor).valid, true)
})

test('update request sends only bounded attrs and leaves read-only attrs server-side', () => {
  const draft = {
    ...draftFromPort(port),
    name: 'pixels',
    direction: 'out',
    portType: 'any',
    label: '',
    shape: '2, 4',
    confidence: 'inferred',
  }
  assert.deepEqual(updateRequestFromDraft(port, draft), {
    name: 'pixels',
    direction: 'out',
    port_type: 'any',
    attrs: {
      shape: [2, 4],
      confidence: 'inferred',
    },
  })
})
