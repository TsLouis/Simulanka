import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { after, test } from 'node:test'

// No browser, Vite server, network, or new test dependency is required.
const source = readFileSync(new URL('../src/lib/events.ts', import.meta.url), 'utf8')
const js = stripTypeScriptTypes(source)
const { subscribeEvents } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`)
const previous = { EventSource: globalThis.EventSource, ErrorEvent: globalThis.ErrorEvent }
class MockSource {
  static last
  listeners = new Map()
  onerror = null
  closeCount = 0
  constructor(url) { assert.equal(url, '/events'); MockSource.last = this }
  addEventListener(name, fn) { this.listeners.set(name, fn) }
  removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name) }
  emit(name, value) { this.listeners.get(name)?.({ data: JSON.stringify(value) }) }
  close() { this.closeCount += 1 }
}
globalThis.EventSource = MockSource
globalThis.ErrorEvent = class extends Event {
  constructor(type, init) { super(type); Object.assign(this, init) }
}
after(() => {
  for (const [name, value] of Object.entries(previous)) {
    if (value === undefined) delete globalThis[name]
    else globalThis[name] = value
  }
})
const commit = { event_id: 'event-1', graph_version: 1, actor: 'user', nodes: ['n1'], edges: [], ports: [] }

function setup() {
  const ready = [], commits = [], errors = []
  const sub = subscribeEvents({ onReady: v => ready.push(v), onCommit: v => commits.push(v), onError: e => errors.push(e) })
  return { ready, commits, errors, sub, es: MockSource.last }
}

test('valid ready v0 and complete commit are delivered', () => {
  const s = setup()
  s.es.emit('ready', { graph_version: 0 })
  s.es.emit('commit', commit)
  assert.deepEqual(s.ready, [0]); assert.deepEqual(s.commits, [commit]); assert.equal(s.errors.length, 0)
  s.sub.close()
})

test('ready frames reject null, arrays, missing, negative, fractional and unsafe versions', () => {
  const s = setup()
  for (const value of [null, [], {}, { graph_version: '1' }, { graph_version: -1 }, { graph_version: 1.5 }, { graph_version: 2 ** 53 }]) s.es.emit('ready', value)
  assert.equal(s.errors.length, 7); assert.deepEqual(s.ready, [])
  s.es.emit('ready', { graph_version: 2 }); assert.deepEqual(s.ready, [2])
  s.sub.close()
})

test('commit frames validate every required field before reaching the App', () => {
  const s = setup()
  const bad = [null, [], {}, { ...commit, event_id: '' }, { ...commit, actor: 1 }, { ...commit, nodes: null }, { ...commit, nodes: [1] }, { ...commit, edges: [''] }, { ...commit, ports: {} }, { ...commit, graph_version: -1 }]
  for (const value of bad) s.es.emit('commit', value)
  assert.equal(s.errors.length, bad.length); assert.equal(s.commits.length, 0)
  s.es.emit('commit', commit); assert.equal(s.commits.length, 1)
  s.sub.close()
})

test('malformed JSON reports one protocol error, keeps listening, and never leaks the frame', () => {
  const s = setup()
  s.es.listeners.get('ready')({ data: '{secret-invalid' })
  s.es.listeners.get('commit')({ data: 'undefined' })
  assert.equal(s.errors.length, 2)
  assert.equal(s.errors[0].type, 'parse')
  assert.ok(!s.errors[0].message.includes('secret'))
  s.es.emit('commit', commit); assert.equal(s.commits.length, 1)
  assert.equal(s.es.closeCount, 0); s.sub.close()
})

test('consumer exceptions are not mislabeled or swallowed as protocol errors', () => {
  const failure = new Error('consumer bug'), errors = []
  const sub = subscribeEvents({ onReady: () => { throw failure }, onCommit: () => { throw failure }, onError: e => errors.push(e) })
  assert.throws(() => MockSource.last.emit('ready', { graph_version: 1 }), e => e === failure)
  assert.throws(() => MockSource.last.emit('commit', commit), e => e === failure)
  assert.equal(errors.length, 0); sub.close()
})

test('network errors leave reconnection to EventSource and later ready frames work', () => {
  const s = setup(), disconnected = new Event('error')
  s.es.onerror(disconnected)
  s.es.emit('ready', { graph_version: 9 })
  assert.deepEqual(s.errors, [disconnected]); assert.deepEqual(s.ready, [9]); assert.equal(s.es.closeCount, 0)
  s.sub.close()
})

test('close is idempotent, detaches listeners and suppresses already queued callbacks', () => {
  const s = setup(), lateCommit = s.es.listeners.get('commit'), lateReady = s.es.listeners.get('ready'), lateError = s.es.onerror
  s.sub.close(); s.sub.close()
  lateCommit({ data: JSON.stringify(commit) }); lateReady({ data: '{"graph_version":1}' }); lateError(new Event('error'))
  assert.equal(s.es.closeCount, 1); assert.equal(s.es.listeners.size, 0); assert.equal(s.es.onerror, null)
  assert.deepEqual([s.ready, s.commits, s.errors], [[], [], []])
})
