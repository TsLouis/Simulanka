import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { LGraphCanvas, LiteGraph } from 'litegraph.js'
import { createServer } from 'vite'

const server = await createServer({ configFile: false, optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true }, appType: 'custom' })
after(() => server.close())
const { buildLiteGraph } = await server.ssrLoadModule('/src/lib/litegraph-adapter.ts')
const { installConnectionFeedback } = await server.ssrLoadModule('/src/lib/connection-feedback.ts')

const semantics = { capabilities: [], unknown_profile: false, affordances: [] }
function fixture(descriptorOverride) {
  const node = (id, capabilities = ['flow']) => ({ ...semantics, id, type: 'module', name: id,
    parent_id: null, attrs: {}, ports: [id], child_count: 0, trust: null, capabilities })
  const port = (id, side) => ({ ...semantics, id, node_id: id, name: id, side, port_type: 'tensor', attrs: {} })
  const descriptor = descriptorOverride === undefined ? {
    aliases: { node: {}, port: {}, edge: {} }, port_types: ['tensor'], node_profiles: [], presentations: [],
    edge_profiles: [{ key: 'data_flow', needs_ports: true, source_profiles: ['*'], target_profiles: ['*'],
      source_capabilities: ['flow'], target_capabilities: ['flow'], source_port_direction: 'out', target_port_direction: 'in' }],
  } : descriptorOverride
  const payload = { root: null, root_info: null, nodes: [node('source'), node('allowed'), node('rejected', [])],
    ports: [port('source', 'out'), port('allowed', 'in'), port('rejected', 'in')], edges: [],
    boundary_edges: [], external_nodes: [], ancestors: [], view_affordances: [] }
  const writes = [], rejections = []
  const result = buildLiteGraph(payload, {
    onCreateEdge: async (...args) => { writes.push(args); return true },
    onConnectionRejected: reason => rejections.push(reason),
  }, { source: [30, 60], allowed: [400, 60], rejected: [400, 250] }, descriptor)
  return { ...result, payload, descriptor, writes, rejections }
}

function canvasFor(graph) {
  const c = new LGraphCanvas(null, graph, { skip_render: true })
  // Keep real native hit tests / mouse processing; replace only the DOM and
  // outer frame. drawNode below still uses LiteGraph 0.7.18's actual renderer.
  c.drawFrontCanvas = () => {}
  c.visible_nodes = graph._nodes
  c.canvas = { style: {}, getBoundingClientRect: () => ({ left: 0, top: 0 }),
    ownerDocument: { defaultView: { document: { addEventListener() {}, removeEventListener() {} } } },
    addEventListener() {}, removeEventListener() {} }
  installConnectionFeedback(c)
  return c
}
function start(c, node, index = 0) {
  c.connecting_node = node
  c.connecting_slot = index
  c.connecting_output = node.outputs[index]
  c.connecting_pos = node.getConnectionPos(false, index)
}
function move(c, position) {
  c.processMouseMove({ clientX: position[0], clientY: position[1], preventDefault() {}, stopPropagation() {} })
  c.drawFrontCanvas()
}
function context() {
  const fills = []
  const ctx = new Proxy({ globalAlpha: 1, fills, measureText: () => ({ width: 20 }),
    fill() { fills.push(this.fillStyle) }, fillRect() { fills.push(this.fillStyle) } }, {
    get: (target, key) => key in target ? target[key] : () => {},
  })
  return ctx
}

test('native mouse movement suppresses Registry rejection, clears stale highlights, preserves hit tests', () => {
  const f = fixture(), c = canvasFor(f.graph)
  const source = f.byNode.get('source'), allowed = f.byNode.get('allowed'), rejected = f.byNode.get('rejected')
  start(c, source)
  move(c, allowed.getConnectionPos(true, 0))
  assert.equal(c._highlight_input_slot, allowed.inputs[0])
  move(c, rejected.getConnectionPos(true, 0))
  assert.equal(c._highlight_input, null)
  assert.equal(c.isOverNodeInput(rejected, ...rejected.getConnectionPos(true, 0)), 0)
  assert.equal(f.rejections.length, 0, 'preview has no validation notifications or writes')
  move(c, allowed.getConnectionPos(true, 0))
  allowed.inputs[0].type = 'string'
  move(c, allowed.getConnectionPos(true, 0))
  assert.equal(c._highlight_input, null, 'native 0.7.18 otherwise leaves a stale datatype highlight')
  move(c, [900, 900])
  assert.equal(c._highlight_input, null)
  assert.equal(f.writes.length, 0)
})

test('native Port rendering marks rejected inputs and restores exact slot metadata', () => {
  const f = fixture(), c = canvasFor(f.graph), target = f.byNode.get('rejected')
  start(c, f.byNode.get('source'))
  const before = structuredClone(target.inputs), pos = [...target.getConnectionPos(true, 0)]
  const ctx = context()
  assert.doesNotThrow(() => c.drawNode(f.byNode.get('source'), context()), 'output-only nodes have no inputs array')
  c.drawNode(target, ctx)
  assert.ok(ctx.fills.includes('#a45b62'))
  assert.deepEqual(target.inputs, before)
  assert.deepEqual([...target.getConnectionPos(true, 0)], pos)
  c.connecting_node = null
  c.connecting_output = null
  const idle = context()
  c.drawNode(target, idle)
  assert.ok(!idle.fills.includes('#a45b62'))
})

test('graph replacement during a drag clears the native orphaned connection fields before drawing', () => {
  const f = fixture(), c = canvasFor(f.graph)
  start(c, f.byNode.get('source'))
  move(c, f.byNode.get('allowed').getConnectionPos(true, 0))
  c.setGraph(fixture().graph)
  assert.equal(c.connecting_node, null)
  assert.notEqual(c.connecting_pos, null, '0.7.18 leaves the old anchor behind')
  c.drawFrontCanvas()
  assert.equal(c.connecting_pos, null)
  assert.equal(c.connecting_output, null)
  assert.equal(c.connecting_input, null)
  assert.equal(c.connecting_slot, -1)
  assert.equal(c._highlight_input, null)
})

test('native drop rejects exact input and valid drops still reach existing persistence', async () => {
  const f = fixture(), c = canvasFor(f.graph)
  const source = f.byNode.get('source'), rejected = f.byNode.get('rejected'), allowed = f.byNode.get('allowed')
  const drop = target => {
    start(c, source)
    const pos = target.getConnectionPos(true, 0)
    move(c, pos)
    c.processMouseUp({ clientX: pos[0], clientY: pos[1], which: 1,
      preventDefault() {}, stopPropagation() {} })
    c.drawFrontCanvas()
  }
  drop(rejected)
  assert.equal(f.writes.length, 0)
  assert.match(f.rejections[0], /capability/)
  drop(allowed)
  await Promise.resolve()
  assert.equal(f.writes.length, 1)
  assert.equal(c.connecting_node, null)
  assert.equal(c._highlight_input, null)
})

test('missing Registry leaves datatype feedback available; unknown profiles reject', () => {
  const f = fixture(null), c = canvasFor(f.graph)
  start(c, f.byNode.get('source'))
  move(c, f.byNode.get('rejected').getConnectionPos(true, 0))
  assert.notEqual(c._highlight_input, null)
  const known = fixture(), c2 = canvasFor(known.graph)
  known.payload.nodes[1].unknown_profile = true
  start(c2, known.byNode.get('source'))
  move(c2, known.byNode.get('allowed').getConnectionPos(true, 0))
  assert.equal(c2._highlight_input, null)
})

test('boundary projection still builds persisted links and deletes by persisted edge id', () => {
  const f = fixture(), deleted = []
  f.payload.root = 'root'
  f.payload.root_info = { ...semantics, id: 'root', type: 'module', name: 'root' }
  f.payload.ports.push({ ...semantics, id: 'root-in', node_id: 'root', name: 'input',
    side: 'in', port_type: 'tensor', attrs: {} })
  f.payload.boundary_edges.push({ ...semantics, id: 'boundary-edge', type: 'data_flow',
    src: 'root', src_port: 'root-in', dst: 'allowed', dst_port: 'allowed', attrs: {} })
  const built = buildLiteGraph(f.payload, { onDeleteEdge: id => deleted.push(id) }, {}, f.descriptor)
  const link = Object.values(built.graph.links)[0]
  assert.equal(link.simulanka_edge_id, 'boundary-edge')
  const c = canvasFor(built.graph), boundary = built.graph.getNodeById(link.origin_id)
  const before = structuredClone(boundary.outputs)
  start(c, boundary)
  c.drawNode(boundary, context())
  assert.deepEqual(boundary.outputs, before)
  built.byNode.get('allowed').disconnectInput(0)
  assert.deepEqual(deleted, ['boundary-edge'])
})

test('render failure restores colors without changing types or the global compatibility function', () => {
  const f = fixture(), c = new LGraphCanvas(null, f.graph, { skip_render: true })
  c.drawNode = () => { throw new Error('draw failed') }
  installConnectionFeedback(c)
  start(c, f.byNode.get('source'))
  const target = f.byNode.get('rejected'), before = structuredClone(target.inputs)
  const check = LiteGraph.isValidConnection
  assert.throws(() => c.drawNode(target, context()), /draw failed/)
  assert.deepEqual(target.inputs, before)
  assert.equal(LiteGraph.isValidConnection, check)
})

test('repeated connect/disconnect and graph replacement keep one wrapper and no execution loops', async () => {
  const c = canvasFor(fixture().graph)
  const wrapper = c.drawFrontCanvas, nativeCheck = LiteGraph.isValidConnection
  for (let i = 0; i < 100; i++) {
    const f = fixture()
    c.setGraph(f.graph)
    c.visible_nodes = f.graph._nodes
    installConnectionFeedback(c)
    start(c, f.byNode.get('source'))
    move(c, f.byNode.get('rejected').getConnectionPos(true, 0))
    assert.equal(c._highlight_input, null)
    const target = f.byNode.get('allowed')
    move(c, target.getConnectionPos(true, 0))
    assert.notEqual(c._highlight_input, null)
    f.byNode.get('source').connect(0, target, 0)
    await Promise.resolve()
    target.disconnectInput(0)
    c.connecting_node = null
    c.connecting_output = null
    c.drawFrontCanvas()
    assert.equal(c._highlight_input, null)
    assert.equal(f.writes.length, 1)
    assert.equal(Object.keys(f.graph.links).length, 0)
    assert.equal(f.graph.status, LiteGraph.LGraph.STATUS_STOPPED)
    assert.equal(c.drawFrontCanvas, wrapper)
    assert.equal(LiteGraph.isValidConnection, nativeCheck)
  }
})
