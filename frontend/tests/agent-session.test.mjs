import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

// Use the app's existing TS loader; exercise controller behavior without a DOM
// or provider process. The API module itself remains unchanged by the cleanup.
const server = await createServer({
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true },
  appType: 'custom',
})
after(() => server.close())
const { createAgentSessionController } = await server.ssrLoadModule('/src/lib/agent-session.ts')

const capabilities = { native_resume: true, native_fork: true, interrupt: true, tool_events: true, usage: true }
const ref = (kind, ref_id) => ({ kind, ref_id })
function session(id, extra = {}) {
  return {
    session_id: id, tree_id: id, scope_root_id: null, scope_status: 'bound',
    provider_id: 'codex', model: null, native_session_id: `native-${id}`,
    workspace: '/fixture', parent_session_id: null, forked_from_event_id: null,
    status: 'done', legacy: false, ...extra,
  }
}
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
function view(controller) {
  let value
  const unsubscribe = controller.subscribe(next => { value = next })
  unsubscribe()
  return value
}
function fixture(sessions = [], initialStorage = {}) {
  const saved = new Map(Object.entries(initialStorage))
  const calls = []
  const history = new Map()
  const data = new Map(sessions.map(item => [item.session_id, item]))
  const client = {
    async fetchSessions(scope) {
      calls.push(['list', scope])
      return [...data.values()].filter(item => scope === 'unassigned'
        ? item.scope_status !== 'bound'
        : item.scope_status === 'bound' && item.scope_root_id === scope)
    },
    async fetchSessionHistory(id) {
      calls.push(['history', id])
      return { session: data.get(id), events: history.get(id) ?? [] }
    },
    async fetchProviderDescriptors() {
      return [
        { provider_id: 'codex', capabilities },
        { provider_id: 'other', capabilities: { ...capabilities, native_resume: false, interrupt: false } },
      ]
    },
    async forkSession(id) {
      calls.push(['fork', id])
      const child = session(`${id}-child`, { ...data.get(id), session_id: `${id}-child`, parent_session_id: id })
      data.set(child.session_id, child)
      return child
    },
    async archiveSession(id) {
      calls.push(['archive', id])
      const archived = { ...data.get(id), status: 'archived' }
      data.set(id, archived)
      return archived
    },
    async stopSession(id) { calls.push(['stop', id]) },
    async previewSessionContext(refs, id) {
      calls.push(['preview', refs, id])
      return { bundle: { refs }, payload: { instruction: [], reference: refs }, sources: refs.map(r => ({ kind: r.kind, id: r.ref_id })), omissions: [], delivery: { action: 'send', reason: 'new' } }
    },
    async streamSessionMessage(options) {
      calls.push(['send', options])
      throw new Error('fixture transport failure')
    },
  }
  // Delegating functions let a test delay one response after initialization.
  const api = Object.fromEntries(Object.keys(client).map(key => [key, (...args) => client[key](...args)]))
  const controller = createAgentSessionController(api, {
    getItem: key => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value),
  })
  return { controller, client, calls, data, history, saved }
}

test('restores tree/branch selection, provider capabilities and complete events without implicit refs', async () => {
  const f = fixture([
    session('a'), session('a-fork', { tree_id: 'a', parent_session_id: 'a' }),
    session('b', { provider_id: 'other' }),
  ], {
    'simulanka.active_session_by_tree': JSON.stringify({ a: 'a-fork' }),
    'simulanka.selected_tree_by_scope': JSON.stringify({ top: 'a' }),
  })
  const events = [
    { type: 'user_msg', text: 'inspect', details: { context_bundles: [{ refs: [ref('node', 'n1')] }] } },
    { type: 'tool_call', tool_name: 'inspect', call_id: 'c1', input: { id: 'n1' } },
    { type: 'tool_result', tool_name: 'inspect', call_id: 'c1', output: { shape: [2, 3] } },
    { type: 'status', status: 'done', details: { usage: { cached_input_tokens: 42 } } },
  ]
  f.history.set('a-fork', events)
  await f.controller.initialize()
  assert.equal(view(f.controller).activeSession.session_id, 'a-fork')
  assert.deepEqual(view(f.controller).events, events)
  assert.deepEqual(view(f.controller).pendingRefs, [])
  assert.equal(view(f.controller).trees.length, 2)
  assert.equal(view(f.controller).capabilities.interrupt, true)
  assert.deepEqual(f.calls.filter(call => call[0] === 'history'), [['history', 'a-fork']])
  await f.controller.openSession('b')
  assert.equal(view(f.controller).providerId, 'other')
  assert.equal(view(f.controller).capabilities.interrupt, false)
  assert.equal(JSON.parse(f.saved.get('simulanka.selected_tree_by_scope')).top, 'b')
})

test('streaming stays with its origin scope, transfers draft refs and retains pinned/new refs after done', async () => {
  const f = fixture([session('elsewhere', { scope_root_id: 'scope-b' })])
  await f.controller.initialize()
  f.controller.addPendingRef(ref('node', 'n1'), 'Node 1')
  f.controller.addPendingRef(ref('node', 'n1'), 'duplicate')
  f.controller.addPendingRef(ref('port', 'p1'), 'Port 1')
  f.controller.togglePendingPin(ref('port', 'p1'))
  await f.controller.previewPendingRefs()
  assert.deepEqual(f.calls.at(-1), ['preview', [ref('node', 'n1'), ref('port', 'p1')], null])
  const gate = deferred()
  let sent
  f.client.streamSessionMessage = async (options, emit) => {
    sent = options
    f.data.set('created', session('created'))
    emit({ type: 'status', status: 'created', details: { session_id: 'created', provider_id: 'codex', workspace: '/fixture' } })
    emit({ type: 'user_msg', text: options.text })
    emit({ type: 'status', status: 'running', provider_session_id: 'native-created' })
    await gate.promise
    emit({ type: 'tool_result', tool_name: 'inspect', output: { ok: true } })
    emit({ type: 'agent_text', text: 'complete' })
    emit({ type: 'status', status: 'done' })
    return 'created'
  }
  const sending = f.controller.sendMessage('inspect these')
  assert.equal(view(f.controller).busy, true)
  assert.equal(view(f.controller).interruptReady, true)
  assert.deepEqual(sent.refs, [ref('node', 'n1'), ref('port', 'p1')])
  assert.equal(sent.scopeRootId, null)
  assert.equal(sent.providerId, 'codex')
  f.controller.addPendingRef(ref('edge', 'late'), 'Attached during the turn')
  await f.controller.setScope('scope-b')
  gate.resolve()
  await sending
  assert.equal(view(f.controller).activeSession.session_id, 'elsewhere')
  assert.deepEqual(view(f.controller).events, [])
  await f.controller.setScope(null)
  assert.equal(view(f.controller).activeSession.session_id, 'created')
  assert.equal(view(f.controller).busy, false)
  assert.deepEqual(view(f.controller).pendingRefs.map(({ kind, ref_id }) => ({ kind, ref_id })), [ref('port', 'p1'), ref('edge', 'late')])
  assert.equal(view(f.controller).events.at(-1).status, 'done')
  assert.deepEqual(view(f.controller).events.find(event => event.type === 'tool_result').output, { ok: true })
})

test('failed and interrupted turns keep explicit refs available for retry', async () => {
  const f = fixture([session('a')])
  await f.controller.initialize()
  f.controller.addPendingRef(ref('edge', 'e1'), 'Edge 1')
  await f.controller.sendMessage('fails')
  assert.match(view(f.controller).events.at(-1).text, /fixture transport failure/)
  assert.equal(view(f.controller).busy, false)
  assert.equal(view(f.controller).pendingRefs.length, 1)
  f.client.streamSessionMessage = async (_options, emit) => {
    emit({ type: 'status', status: 'interrupted' })
    return 'a'
  }
  await f.controller.sendMessage('interrupted')
  assert.equal(view(f.controller).activeSession.status, 'interrupted')
  assert.equal(view(f.controller).pendingRefs.length, 1)
})

test('late previews cannot follow refs or the native branch they were compiled for', async () => {
  const f = fixture([session('a'), session('child', { tree_id: 'a', parent_session_id: 'a' })])
  await f.controller.initialize()
  f.controller.addPendingRef(ref('node', 'n1'), 'Node 1')
  const gate = deferred()
  f.client.previewSessionContext = () => gate.promise
  const pending = f.controller.previewPendingRefs()
  await f.controller.openSession('child')
  gate.resolve({ delivery: { action: 'skip' }, payload: { reference: ['stale'] } })
  await pending
  assert.equal(view(f.controller).preview, null)
  assert.equal(view(f.controller).previewBusy, false)
  assert.equal(view(f.controller).pendingRefs.length, 1)
  const removed = deferred()
  f.client.previewSessionContext = () => removed.promise
  const second = f.controller.previewPendingRefs()
  f.controller.removePendingRef(ref('node', 'n1'))
  removed.resolve({ delivery: { action: 'send' } })
  await second
  assert.equal(view(f.controller).preview, null)
  assert.deepEqual(view(f.controller).pendingRefs, [])
})

test('older list/history snapshots cannot overwrite a newly streamed turn', async () => {
  const f = fixture([session('a')])
  await f.controller.initialize()
  const list = deferred()
  const history = deferred()
  f.client.fetchSessions = () => list.promise
  f.client.fetchSessionHistory = () => history.promise
  const refresh = f.controller.restoreSessions()
  const opening = f.controller.openSession('a')
  f.client.streamSessionMessage = async (_options, emit) => {
    emit({ type: 'agent_text', text: 'new answer' })
    emit({ type: 'status', status: 'done' })
    return 'a'
  }
  await f.controller.sendMessage('new turn')
  list.resolve([session('a', { status: 'archived' })])
  history.resolve({ session: session('a', { status: 'running' }), events: [{ type: 'agent_text', text: 'old' }] })
  await Promise.all([refresh, opening])
  assert.equal(view(f.controller).activeSession.status, 'done')
  assert.equal(view(f.controller).events[0].text, 'new answer')
  assert.equal(view(f.controller).listBusy, false)
})

test('fork/archive preserve tree identity and recovery never binds unassigned sessions', async () => {
  const f = fixture([session('a'), session('recovery', { scope_status: 'broken' })])
  const audit = [{ type: 'tool_result', output: { recovered: true }, details: { context_bundles: [] } }]
  f.history.set('recovery', audit)
  await f.controller.initialize()
  f.controller.addPendingRef(ref('port', 'p1'), 'Port 1')
  await f.controller.previewPendingRefs()
  await f.controller.forkActiveSession('a')
  assert.equal(view(f.controller).activeSession.session_id, 'a-child')
  assert.equal(view(f.controller).selectedTreeId, 'a')
  assert.equal(view(f.controller).pendingRefs.length, 1)
  assert.equal(view(f.controller).preview, null)
  await f.controller.archiveActiveSession('a')
  assert.equal(view(f.controller).readOnly, true)
  await f.controller.sendMessage('read-only must not send')
  assert.equal(f.calls.some(call => call[0] === 'send'), false)
  await f.controller.openRecovery()
  assert.equal(view(f.controller).recovery.sessionId, 'recovery')
  assert.deepEqual(view(f.controller).recovery.events, audit)
  assert.equal(view(f.controller).trees.length, 1)
  assert.equal(view(f.controller).activeSession.session_id, 'a-child')
  assert.ok(f.calls.some(call => call[0] === 'list' && call[1] === 'unassigned'))
})

test('stop targets the active native branch and terminal events clear stopping state', async () => {
  const f = fixture([session('a')])
  await f.controller.initialize()
  const gate = deferred()
  f.client.streamSessionMessage = async (_options, emit) => {
    emit({ type: 'status', status: 'running', provider_session_id: 'native-a' })
    await gate.promise
    emit({ type: 'status', status: 'interrupted' })
    return 'a'
  }
  const sending = f.controller.sendMessage('work')
  await f.controller.stopActiveSession('a')
  assert.equal(view(f.controller).stopping, true)
  assert.deepEqual(f.calls.at(-1), ['stop', 'a'])
  gate.resolve()
  await sending
  assert.equal(view(f.controller).stopping, false)
  assert.equal(view(f.controller).activeSession.status, 'interrupted')
})
