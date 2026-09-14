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

const { CreateReloadGate } = await server.ssrLoadModule('/src/lib/create-reload-gate.ts')

test('idle commits are never deferred', () => {
  const gate = new CreateReloadGate()
  assert.equal(gate.busy, false)
  assert.equal(gate.deferIfBusy(), false)
  assert.equal(gate.finish(), false)
})

test('one create releases one coalesced deferred reload', () => {
  const gate = new CreateReloadGate()
  gate.begin()
  assert.equal(gate.busy, true)
  assert.equal(gate.deferIfBusy(), true)
  assert.equal(gate.deferIfBusy(), true, 'several SSE commits still coalesce')
  assert.equal(gate.finish(), true)
  assert.equal(gate.busy, false)
  assert.equal(gate.finish(), false, 'release is emitted only once')
})

test('overlapping creates wait for the last handoff', () => {
  const gate = new CreateReloadGate()
  gate.begin()
  gate.begin()
  assert.equal(gate.pendingCount, 2)
  assert.equal(gate.deferIfBusy(), true)
  assert.equal(gate.finish(), false)
  assert.equal(gate.pendingCount, 1)
  assert.equal(gate.deferIfBusy(), true)
  assert.equal(gate.finish(), true)
  assert.equal(gate.pendingCount, 0)
})

test('no creation-triggered commit means no unnecessary reload release', () => {
  const gate = new CreateReloadGate()
  gate.begin()
  assert.equal(gate.finish(), false)
})

test('a later create burst can defer and release again', () => {
  const gate = new CreateReloadGate()
  gate.begin()
  gate.deferIfBusy()
  assert.equal(gate.finish(), true)

  gate.begin()
  gate.begin()
  gate.deferIfBusy()
  assert.equal(gate.finish(), false)
  assert.equal(gate.finish(), true)
})
