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
  conversationProjectionFromEvents,
  stripProjectionBlocks,
} = await server.ssrLoadModule('/src/lib/agent-projection.ts')

const block = payload => '```simulanka-projection\n' + JSON.stringify(payload) + '\n```'

const userEvent = refs => ({
  type: 'user_msg',
  details: { context_bundles: [{ refs }] },
})

test('uses only the latest user turn explicit ContextBundle refs', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([{ kind: 'node', ref_id: 'old' }]),
    { type: 'agent_text', text: 'old answer' },
    userEvent([
      { kind: 'node', ref_id: 'n1' },
      { kind: 'edge', ref_id: 'e1' },
      { kind: 'node', ref_id: 'n1' },
    ]),
    { type: 'status', status: 'running' },
    { type: 'agent_text', text: 'new answer' },
  ])

  assert.deepEqual(projection, {
    refs: [
      { kind: 'node', ref_id: 'n1' },
      { kind: 'edge', ref_id: 'e1' },
    ],
    text: 'new answer',
    visuals: [],
  })
})

test('does not infer projection targets from prose or selection-like details', () => {
  const projection = conversationProjectionFromEvents([
    { type: 'user_msg', text: 'look at node n1' },
    { type: 'agent_text', text: 'I think n1 is suspicious' },
  ])
  assert.deepEqual(projection, { refs: [], text: null, visuals: [] })
})

test('ignores malformed context refs', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([
      { kind: 'node', ref_id: '' },
      { kind: 'file', ref_id: 'x' },
      { kind: 'port', ref_id: 'p1' },
    ]),
  ])
  assert.deepEqual(projection, {
    refs: [{ kind: 'port', ref_id: 'p1' }],
    text: null,
    visuals: [],
  })
})

test('a newer turn without explicit refs clears the previous graph projection', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([{ kind: 'node', ref_id: 'n1' }]),
    { type: 'agent_text', text: 'about n1' },
    { type: 'user_msg', text: 'now answer generally' },
    { type: 'agent_text', text: 'general answer' },
  ])
  assert.deepEqual(projection, { refs: [], text: null, visuals: [] })
})

test('structured attention can only target refs actually delivered in this turn', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([
      { kind: 'node', ref_id: 'n1' },
      { kind: 'edge', ref_id: 'e1' },
    ]),
    {
      type: 'agent_text',
      text: `Look here.\n\n${block({
        kind: 'attention',
        refs: [
          { kind: 'node', ref_id: 'n1' },
          { kind: 'node', ref_id: 'invented' },
          { kind: 'edge', ref_id: 'e1' },
        ],
        label: 'critical relation',
      })}`,
    },
  ])

  assert.equal(projection.text, 'Look here.')
  assert.deepEqual(projection.visuals, [{
    kind: 'attention',
    refs: [
      { kind: 'node', ref_id: 'n1' },
      { kind: 'edge', ref_id: 'e1' },
    ],
    label: 'critical relation',
  }])
})

test('annotation with a target outside explicit context is rejected', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([{ kind: 'port', ref_id: 'p1' }]),
    {
      type: 'agent_text',
      text: block({
        kind: 'annotation',
        target: { kind: 'edge', ref_id: 'e9' },
        text: 'not allowed',
      }),
    },
  ])

  assert.deepEqual(projection.visuals, [])
})

test('draft graph uses local sketch ids but requires an explicit real anchor', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([{ kind: 'node', ref_id: 'n1' }]),
    {
      type: 'agent_text',
      text: `One possible experiment:\n${block({
        kind: 'draft_graph',
        anchor: { kind: 'node', ref_id: 'n1' },
        nodes: [
          { id: 'h', label: 'Alternative hypothesis', type: 'hypothesis' },
          { id: 'x', label: 'Discriminating experiment', type: 'experiment' },
        ],
        edges: [
          { src: 'h', dst: 'x', label: 'test with' },
          { src: 'h', dst: 'missing', label: 'ignored' },
        ],
      })}`,
    },
  ])

  const [visual] = projection.visuals
  assert.equal(visual.kind, 'draft_graph')
  assert.deepEqual(visual.anchor, { kind: 'node', ref_id: 'n1' })
  assert.deepEqual(visual.nodes.map(node => node.id), ['h', 'x'])
  assert.deepEqual(visual.edges, [{ src: 'h', dst: 'x', label: 'test with' }])
})

test('projection protocol is stripped from human-readable transcript text', () => {
  const raw = `Answer first.\n\n${block({
    kind: 'attention',
    refs: [{ kind: 'node', ref_id: 'n1' }],
  })}\n\nMore prose.`
  assert.equal(stripProjectionBlocks(raw), 'Answer first.\n\nMore prose.')
})

test('projection fenced JSON can stream across multiple agent_text chunks', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([{ kind: 'node', ref_id: 'n1' }]),
    { type: 'agent_text', text: 'Look here.\n\n```simulanka-projection\n{"kind":"attention",' },
    { type: 'agent_text', text: '"refs":[{"kind":"node","ref_id":"n1"}]}' },
    { type: 'agent_text', text: '\n```' },
  ])

  assert.equal(projection.text, 'Look here.')
  assert.deepEqual(projection.visuals, [{
    kind: 'attention',
    refs: [{ kind: 'node', ref_id: 'n1' }],
    label: null,
  }])
})

test('an unfinished projection fence never leaks partial protocol JSON into visible text', () => {
  const raw = 'Readable answer.\n\n```simulanka-projection\n{"kind":"annotation"'
  assert.equal(stripProjectionBlocks(raw), 'Readable answer.')
})

test('attention de-duplicates repeated refs and bounds a crowded visual', () => {
  const refs = Array.from({ length: 14 }, (_, index) => ({
    kind: 'node',
    ref_id: `n${index + 1}`,
  }))
  const projection = conversationProjectionFromEvents([
    userEvent(refs),
    {
      type: 'agent_text',
      text: block({
        kind: 'attention',
        refs: [refs[0], refs[0], ...refs.slice(1)],
      }),
    },
  ])

  const [visual] = projection.visuals
  assert.equal(visual.kind, 'attention')
  assert.equal(visual.refs.length, 12)
  assert.equal(new Set(visual.refs.map(ref => `${ref.kind}:${ref.ref_id}`)).size, 12)
  assert.deepEqual(visual.refs[0], refs[0])
})

test('draft graph de-duplicates local ids and edges and enforces sketch size bounds', () => {
  const projection = conversationProjectionFromEvents([
    userEvent([{ kind: 'node', ref_id: 'n1' }]),
    {
      type: 'agent_text',
      text: block({
        kind: 'draft_graph',
        anchor: { kind: 'node', ref_id: 'n1' },
        nodes: [
          { id: 'a', label: 'A' },
          { id: 'a', label: 'Duplicate A' },
          { id: 'b', label: 'B' },
          { id: 'c', label: 'C' },
          { id: 'd', label: 'D' },
          { id: 'e', label: 'E' },
          { id: 'f', label: 'F' },
          { id: 'g', label: 'G should be truncated' },
        ],
        edges: [
          { src: 'a', dst: 'b', label: 'x' },
          { src: 'a', dst: 'b', label: 'x' },
          { src: 'b', dst: 'c', label: 'y' },
          { src: 'c', dst: 'd', label: 'z' },
          { src: 'd', dst: 'e' },
          { src: 'e', dst: 'f' },
          { src: 'f', dst: 'a' },
          { src: 'a', dst: 'c' },
          { src: 'b', dst: 'd' },
          { src: 'c', dst: 'e' },
          { src: 'a', dst: 'g', label: 'invalid after truncation' },
        ],
      }),
    },
  ])

  const [visual] = projection.visuals
  assert.equal(visual.kind, 'draft_graph')
  assert.deepEqual(visual.nodes.map(node => node.id), ['a', 'b', 'c', 'd', 'e', 'f'])
  assert.equal(visual.edges.length, 8)
  assert.equal(
    new Set(visual.edges.map(edge => `${edge.src}:${edge.dst}:${edge.label ?? ''}`)).size,
    visual.edges.length,
  )
  assert.equal(visual.edges.some(edge => edge.dst === 'g'), false)
})
