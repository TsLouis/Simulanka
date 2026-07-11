// Adapter from Simulanka {nodes, edges, boundary_edges, external_nodes, ports}
// payload → LiteGraph graph. Implements docs/design.md §12.3 (drill-down) and
// §12.4 (boundary-port projection). The adapter is pure rendering: virtual
// boundary nodes never enter graph state.

import dagre from 'dagre'
import { LiteGraph, LGraph, type LGraphNode } from 'litegraph.js'
import { CARD_LINE_H, CARD_WIDTH, cardLines, type CardLine } from './cards'
import {
  EDGE_COLORS,
  GHOST_COLOR,
  INFERRED_COLOR,
  REJECTED_GHOST_COLOR,
  styleNode,
  VERIFIED_COLOR,
} from './theme'
import type {
  EdgeDTO,
  ExternalNodeDTO,
  GraphPayload,
  NodeDTO,
  PortDTO,
  ShapeCheck,
} from './types'

// LiteGraph link object (untyped in @types). We stash our edge id on it so a
// later disconnect knows which persisted edge to delete.
interface LiteLink {
  id: number
  origin_id: number
  origin_slot: number
  target_id: number
  target_slot: number
  simulanka_edge_id?: string
  // §13.5.3 ghost: an agent proposal not yet confirmed. Rendered gray + dashed
  // so a draft never reads as a committed edge (App.svelte dashes these).
  simulanka_ghost?: boolean
  // §13.5.6: the sub-slice this edge carries out of its source port (`[-1]` /
  // `[:-1]`). When a module sends different outputs to different consumers from
  // one port, the label is what tells the two edges apart (App.svelte draws it).
  simulanka_slice?: string
  color?: string
}

// Link colour by edge provenance (§13.5.2): machine-traced vs human-drawn vs
// agent-asserted, so the three read apart at a glance. LiteGraph honours
// `link.color` in renderLink. Palette lives in theme.ts (星图册: trace=星蓝,
// user=金线, agent=紫晶; ghost=灰蓝低语, rejected=绯红).

const TYPE_PREFIX = 'simulanka/'
const BOUNDARY_PREFIX = 'simulanka-boundary/'

// Approximate per-node footprint for dagre layout. Real LiteGraph nodes
// auto-size to title + slots, but dagre needs a number up front.
const NODE_W = 200
const NODE_H = 100

export interface AdapterCallbacks {
  onDrillDown?: (nodeId: string, nodeName: string) => void
  onJumpExternal?: (externalId: string, externalName: string) => void
  // User drew a connection (§13.5.2). Resolve true to keep it (it will be
  // persisted), false to undo the canvas link (e.g. the user cancelled a
  // shape-mismatch confirm).
  onCreateEdge?: (
    srcPortId: string,
    dstPortId: string,
    shapeCheck: ShapeCheck,
  ) => Promise<boolean>
  // User removed a connection that maps to a persisted edge.
  onDeleteEdge?: (edgeId: string) => void
}

export interface AdapterResult {
  graph: LGraph
  byNode: Map<string, LGraphNode>
}

function ensureRegistered(typeName: string, prefix: string = TYPE_PREFIX): string {
  const full = prefix + typeName
  if (LiteGraph.registered_node_types[full]) return full
  function NodeCtor(this: LGraphNode) {}
  ;(NodeCtor as unknown as { title: string }).title = typeName
  LiteGraph.registerNodeType(full, NodeCtor as unknown as new () => LGraphNode)
  return full
}

export function buildLiteGraph(
  payload: GraphPayload,
  callbacks: AdapterCallbacks = {},
  persistedPositions: Record<string, [number, number]> = {},
): AdapterResult {
  const graph = new LGraph()
  const portsById = new Map<string, PortDTO>(payload.ports.map(p => [p.id, p]))

  const inSlot = new Map<string, number>()
  const outSlot = new Map<string, number>()
  const byNode = new Map<string, LGraphNode>()

  // While the adapter wires up the payload's own edges, LiteGraph fires
  // onConnectionsChange too — suppress handling until the initial build is done
  // so only genuinely user-drawn connections reach the callbacks.
  let building = true
  const INPUT = (LiteGraph as unknown as { INPUT: number }).INPUT

  // Installed on every real node. Acts only from the target (INPUT) side so a
  // connection is handled exactly once. Connect → ask the host to persist
  // (undo on a rejected confirm); disconnect → delete the mapped edge.
  function onConnectionsChange(
    this: LGraphNode,
    type: number,
    slot: number,
    connected: boolean,
    link: LiteLink | undefined,
  ): void {
    if (building || type !== INPUT || !link) return
    const target = this
    if (connected) {
      const g = graph as unknown as { getNodeById: (id: number) => LGraphNode | null }
      const srcNode = g.getNodeById(link.origin_id)
      const srcPortId = srcNode
        ? (srcNode as unknown as { simulanka_out_ports?: string[] })
            .simulanka_out_ports?.[link.origin_slot]
        : undefined
      const dstPortId = (target as unknown as { simulanka_in_ports?: string[] })
        .simulanka_in_ports?.[slot]
      const create = callbacks.onCreateEdge
      if (!srcPortId || !dstPortId || !create) {
        // Unresolvable endpoint — e.g. one end is a boundary-stub slot, which
        // carries no simulanka ports. Undo the canvas link instead of leaving
        // an unpersisted line that lies about graph state. Deferred: LiteGraph
        // is still inside connect() when this handler fires.
        queueMicrotask(() => {
          (target as unknown as { disconnectInput: (s: number) => void }).disconnectInput(slot)
        })
        return
      }
      const sc = computeShapeCheck(portsById.get(srcPortId), portsById.get(dstPortId))
      void create(srcPortId, dstPortId, sc).then(keep => {
        if (!keep) {
          (target as unknown as { disconnectInput: (s: number) => void }).disconnectInput(slot)
        }
      })
    } else if (link.simulanka_edge_id && callbacks.onDeleteEdge) {
      callbacks.onDeleteEdge(link.simulanka_edge_id)
    }
  }

  // Auto-layout: dagre runs over real nodes + their internal data-flow edges.
  // Persisted positions in persistedPositions override the dagre result, so
  // user-dragged nodes stick across reloads.
  const autoPos = computeAutoLayout(payload)

  payload.nodes.forEach((n: NodeDTO) => {
    const isContainer = n.child_count > 0
    const lgnode = LiteGraph.createNode(ensureRegistered(n.type)) as LGraphNode
    lgnode.title = isContainer ? `▸ ${n.name}` : n.name
    styleNode(lgnode, n.type)
    ;(lgnode as unknown as { simulanka: NodeDTO }).simulanka = n

    let inI = 0
    let outI = 0
    // Slot-index → port-id, in slot order, so the connection handler can map a
    // LiteGraph link back to our port ids.
    const inPorts: string[] = []
    const outPorts: string[] = []
    for (const portId of n.ports) {
      const p = portsById.get(portId)
      if (!p) continue
      // Display the semantic label (param/kwarg/dict key) over the structural
      // slot name when present, with the observed shape appended. Colour the
      // slot dot by confidence so `inferred` (unverified) ports read as muted —
      // the honest-labelling guarantee of §13.3.1 made visible.
      const extra = slotExtra(p)
      if (p.side === 'in') {
        lgnode.addInput(p.name, p.port_type || '*', extra)
        inSlot.set(portId, inI)
        inPorts[inI] = portId
        inI++
      } else {
        lgnode.addOutput(p.name, p.port_type || '*', extra)
        outSlot.set(portId, outI)
        outPorts[outI] = portId
        outI++
      }
    }
    ;(lgnode as unknown as { simulanka_in_ports: string[] }).simulanka_in_ports = inPorts
    ;(lgnode as unknown as { simulanka_out_ports: string[] }).simulanka_out_ports = outPorts
    ;(lgnode as unknown as { onConnectionsChange: typeof onConnectionsChange })
      .onConnectionsChange = onConnectionsChange

    // S5 卡片：attr 驱动的展示模板（cards.ts 是唯一的字段清单来源）。
    const card = cardLines(n)
    if (card.length > 0) attachCard(lgnode, card)

    const pos = persistedPositions[n.id] ?? autoPos.get(n.id) ?? [80, 80]
    lgnode.pos = [pos[0], pos[1]]

    if (isContainer && callbacks.onDrillDown) {
      const cb = callbacks.onDrillDown
      ;(lgnode as unknown as { onDblClick: () => void }).onDblClick = () => {
        cb(n.id, n.name)
      }
    }

    graph.add(lgnode)
    byNode.set(n.id, lgnode)
  })

  // Internal edges: both endpoints inside. Only data-flow-shaped edges (those
  // with ports on both sides) render as visible connections; structural edges
  // like `contains` are implicit in the subgraph nesting and intentionally
  // not drawn (see §12.3).
  for (const e of payload.edges) {
    const link = connectViaPorts(e, byNode, inSlot, outSlot)
    if (link) decorateLink(link, e)
  }

  // Cross-boundary edges → virtual boundary nodes (§12.4). One boundary node
  // per (externalId, direction) pair; aggregates all edges to/from that
  // external endpoint as slots.
  if (payload.root !== null && payload.boundary_edges.length > 0) {
    injectBoundary(
      graph,
      payload.boundary_edges,
      payload.external_nodes,
      byNode,
      inSlot,
      outSlot,
      portsById,
      callbacks,
      onConnectionsChange,
    )
  }

  building = false
  return { graph, byNode }
}

// --- S5 card rendering -------------------------------------------------------
// One drawing skeleton for every atom type; cards.ts owns the per-type field
// lists. The card area sits below the slot rows; node height is expanded to
// make room, and onDrawForeground paints the lines.

interface CardStash {
  lines: CardLine[]
  top: number
}

function attachCard(lgnode: LGraphNode, lines: CardLine[]): void {
  const base = lgnode.computeSize()
  const top = base[1] + 6
  lgnode.size = [Math.max(base[0], CARD_WIDTH), top + lines.length * CARD_LINE_H + 8]
  ;(lgnode as unknown as { simulanka_card: CardStash }).simulanka_card = { lines, top }
  ;(lgnode as unknown as {
    onDrawForeground: (ctx: CanvasRenderingContext2D) => void
  }).onDrawForeground = drawCardForeground
}

function drawCardForeground(this: LGraphNode, ctx: CanvasRenderingContext2D): void {
  const self = this as unknown as {
    simulanka_card?: CardStash
    flags?: { collapsed?: boolean }
  }
  const stash = self.simulanka_card
  if (!stash || self.flags?.collapsed) return
  let y = stash.top + 11
  ctx.save()
  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  for (const line of stash.lines) {
    if (line.kind === 'badges') {
      let x = 10
      ctx.font = "600 9px 'Noto Sans SC', ui-sans-serif, sans-serif"
      for (const b of line.badges) {
        const tw = ctx.measureText(b.text).width
        const bw = tw + 12
        ctx.beginPath()
        ctx.roundRect(x, y - 9.5, bw, 13, 6.5)
        ctx.fillStyle = withAlpha(b.color, 0.16)
        ctx.fill()
        ctx.strokeStyle = withAlpha(b.color, 0.55)
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.fillStyle = b.color
        ctx.fillText(b.text, x + 6, y + 0.5)
        x += bw + 6
      }
    } else {
      ctx.font = line.mono
        ? '10px ui-monospace, monospace'
        : "11px 'Noto Sans SC', ui-sans-serif, sans-serif"
      ctx.fillStyle = line.dim ? '#8d99b5' : '#c9d2e4'
      ctx.fillText(line.text, 10, y + 1)
    }
    y += CARD_LINE_H
  }
  ctx.restore()
}

function withAlpha(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// Stamp a LiteGraph link with the persisted edge's identity and provenance
// styling. Applies to internal edges and boundary-stub projections alike
// (§12.4): a stub link carries the real edge id, so disconnecting it deletes
// the real edge instead of silently diverging from the store, and a proposed
// cross-boundary edge still reads as a ghost inside a drill-down view.
function decorateLink(link: LiteLink, e: EdgeDTO): void {
  link.simulanka_edge_id = e.id
  const src = typeof e.attrs.source === 'string' ? e.attrs.source : null
  if (e.attrs.status === 'proposed') {
    link.simulanka_ghost = true
    link.color =
      e.attrs.verdict === 'wrong' && e.attrs.verdict_by === 'user'
        ? REJECTED_GHOST_COLOR
        : GHOST_COLOR
  } else if (src && EDGE_COLORS[src]) {
    link.color = EDGE_COLORS[src]
  }
  // §13.5.6: carry the output-slice onto the link so two edges leaving the
  // same port (e.g. image_encoder `[-1]` vs `[:-1]`) render distinguishably.
  if (typeof e.attrs.output_slice === 'string') {
    link.simulanka_slice = e.attrs.output_slice
  }
}

// Draw-time shape verdict (§13.5.2). Only verified↔verified ports with shapes
// get a definite match/mismatch; anything inferred or shapeless is `unknown`.
function computeShapeCheck(src?: PortDTO, dst?: PortDTO): ShapeCheck {
  if (!src || !dst) return 'unknown'
  const ss = Array.isArray(src.attrs.shape) ? (src.attrs.shape as number[]) : null
  const ds = Array.isArray(dst.attrs.shape) ? (dst.attrs.shape as number[]) : null
  if (!ss || !ds || src.attrs.confidence !== 'verified' || dst.attrs.confidence !== 'verified') {
    return 'unknown'
  }
  return ss.length === ds.length && ss.every((v, i) => v === ds[i]) ? 'match' : 'mismatch'
}

// Confidence palette: verified slots read as live (jade), inferred as muted
// grey-blue. Values from theme.ts so inspector chips and slot dots agree.

// Build the LiteGraph slot `extra_info`: a display `label` (semantic name +
// observed shape) and a confidence-coded dot colour. A port that declares no
// `confidence` keeps LiteGraph's default dot — we never paint it green, since
// green means "verified" and §13.3.1 forbids implying we observed a port we
// didn't (non-importer ports created via CLI/agent fall here).
function slotExtra(p: PortDTO): Record<string, unknown> {
  const label = typeof p.attrs.label === 'string' ? p.attrs.label : null
  const shape = Array.isArray(p.attrs.shape) ? (p.attrs.shape as number[]).join('×') : null
  const display = [label ?? p.name, shape ? `(${shape})` : null].filter(Boolean).join(' ')
  const extra: Record<string, unknown> = { label: display }
  if (p.attrs.confidence === 'verified') {
    extra.color_on = VERIFIED_COLOR
    extra.color_off = VERIFIED_COLOR
  } else if (p.attrs.confidence === 'inferred') {
    extra.color_on = INFERRED_COLOR
    extra.color_off = INFERRED_COLOR
  }
  return extra
}

function connectViaPorts(
  e: EdgeDTO,
  byNode: Map<string, LGraphNode>,
  inSlot: Map<string, number>,
  outSlot: Map<string, number>,
): LiteLink | null {
  if (!e.src_port || !e.dst_port) return null
  const srcNode = byNode.get(e.src)
  const dstNode = byNode.get(e.dst)
  if (!srcNode || !dstNode) return null
  const out = outSlot.get(e.src_port)
  const inp = inSlot.get(e.dst_port)
  if (out === undefined || inp === undefined) return null
  return srcNode.connect(out, dstNode, inp) as unknown as LiteLink | null
}

interface BoundaryBucket {
  externalId: string
  externalName: string
  direction: 'in' | 'out' // 'in' = external feeds internal (left); 'out' = internal feeds external (right)
  edges: EdgeDTO[]
}

function injectBoundary(
  graph: LGraph,
  boundaryEdges: EdgeDTO[],
  externalNodes: ExternalNodeDTO[],
  byNode: Map<string, LGraphNode>,
  inSlot: Map<string, number>,
  outSlot: Map<string, number>,
  portsById: Map<string, PortDTO>,
  callbacks: AdapterCallbacks,
  onConnectionsChange: (
    this: LGraphNode,
    type: number,
    slot: number,
    connected: boolean,
    link: LiteLink | undefined,
  ) => void,
): void {
  const externalById = new Map<string, ExternalNodeDTO>(
    externalNodes.map(x => [x.id, x]),
  )

  // Group by (external endpoint id, direction relative to subgraph). Only
  // port-bearing edges qualify for boundary-port projection — structural
  // edges (contains, supports) cross the boundary too, but they have no
  // port to project onto and the nesting itself already conveys them.
  const buckets = new Map<string, BoundaryBucket>()
  for (const e of boundaryEdges) {
    if (!e.src_port || !e.dst_port) continue
    const srcInside = byNode.has(e.src)
    const dstInside = byNode.has(e.dst)
    if (srcInside === dstInside) continue
    const externalId = srcInside ? e.dst : e.src
    const direction: 'in' | 'out' = srcInside ? 'out' : 'in'
    const key = `${direction}:${externalId}`
    const ext = externalById.get(externalId)
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = {
        externalId,
        externalName: ext?.name ?? externalId,
        direction,
        edges: [],
      }
      buckets.set(key, bucket)
    }
    bucket.edges.push(e)
  }

  // Lay out boundary nodes in columns hugging the real-node bounding box.
  // Left column for inbound (external → internal), right column for outbound.
  let minX = Infinity
  let maxX = -Infinity
  for (const ln of byNode.values()) {
    const [x] = ln.pos
    if (x < minX) minX = x
    if (x > maxX) maxX = x
  }
  if (!Number.isFinite(minX)) { minX = 80; maxX = 80 }
  const leftX = minX - 260
  const rightX = maxX + NODE_W + 40
  let inboundIdx = 0
  let outboundIdx = 0

  for (const bucket of buckets.values()) {
    const lgnode = LiteGraph.createNode(
      ensureRegistered(bucket.direction === 'in' ? 'inbound' : 'outbound', BOUNDARY_PREFIX),
    ) as LGraphNode
    lgnode.title = bucket.direction === 'in'
      ? `← from ${bucket.externalName}`
      : `→ to ${bucket.externalName}`
    styleNode(lgnode, 'boundary')
    ;(lgnode as unknown as { simulanka_boundary: BoundaryBucket }).simulanka_boundary =
      bucket
    // Boundary nodes can't be moved or selected like real nodes — they're a
    // rendering of the subgraph frame. LiteGraph doesn't expose a clean "lock"
    // API; the visual fixed-column placement is enough for MVP.
    // The connection handler must live here too: for outbound buckets the
    // INPUT side of a stub link is the boundary node itself, so a disconnect
    // there would otherwise never reach onDeleteEdge.
    ;(lgnode as unknown as { onConnectionsChange: typeof onConnectionsChange })
      .onConnectionsChange = onConnectionsChange

    // Per-edge slots so the user can see which internal port each cross-edge
    // attaches to. Slot direction is the boundary node's local view:
    //   inbound  bucket: each edge has one OUTPUT slot (feeds an internal IN port)
    //   outbound bucket: each edge has one INPUT slot  (receives from internal OUT port)
    bucket.edges.forEach((e, i) => {
      const otherPortId = bucket.direction === 'in' ? e.src_port : e.dst_port
      const label = otherPortId
        ? portsById.get(otherPortId)?.name ?? `port${i}`
        : `port${i}`
      if (bucket.direction === 'in') {
        lgnode.addOutput(label, '*')
      } else {
        lgnode.addInput(label, '*')
      }
    })

    const col = bucket.direction === 'in' ? leftX : rightX
    const row = 80 + (bucket.direction === 'in' ? inboundIdx++ : outboundIdx++) * 120
    lgnode.pos = [col, row]

    if (callbacks.onJumpExternal) {
      const cb = callbacks.onJumpExternal
      const { externalId, externalName } = bucket
      ;(lgnode as unknown as { onDblClick: () => void }).onDblClick = () => {
        cb(externalId, externalName)
      }
    }

    graph.add(lgnode)

    // Wire each boundary-node slot to the internal node's real port slot.
    // Decorated like internal links: the stub link carries the real edge id
    // (disconnect = persisted DELETE) and the edge's ghost/provenance styling.
    bucket.edges.forEach((e, i) => {
      let link: LiteLink | null = null
      if (bucket.direction === 'in') {
        // boundary.out[i] → internal_dst.in[dst_port]
        const dstNode = byNode.get(e.dst)
        if (!dstNode || !e.dst_port) return
        const inp = inSlot.get(e.dst_port)
        if (inp === undefined) return
        link = lgnode.connect(i, dstNode, inp) as unknown as LiteLink | null
      } else {
        // internal_src.out[src_port] → boundary.in[i]
        const srcNode = byNode.get(e.src)
        if (!srcNode || !e.src_port) return
        const out = outSlot.get(e.src_port)
        if (out === undefined) return
        link = srcNode.connect(out, lgnode, i) as unknown as LiteLink | null
      }
      if (link) decorateLink(link, e)
    })
  }
}

// dagre lays out the real nodes left-to-right (LR), driven by data-flow edges.
// Nodes with no edges fall into their own rank column. Returns absolute (x, y)
// positions keyed by node id; the caller may override with persisted values.
function computeAutoLayout(payload: GraphPayload): Map<string, [number, number]> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90, marginx: 40, marginy: 40 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const n of payload.nodes) {
    // Card lines grow the node vertically — feed dagre the real footprint so
    // stacked (edge-less) atoms don't overlap.
    g.setNode(n.id, {
      width: NODE_W,
      height: NODE_H + cardLines(n).length * CARD_LINE_H,
    })
  }
  // Only real (both-endpoints-in) edges drive layout. Contains/structural edges
  // are implicit in nesting and shouldn't affect rank.
  for (const e of payload.edges) {
    if (e.type !== 'data_flow') continue
    if (!g.hasNode(e.src) || !g.hasNode(e.dst)) continue
    g.setEdge(e.src, e.dst)
  }

  dagre.layout(g)

  const out = new Map<string, [number, number]>()
  for (const id of g.nodes()) {
    const node = g.node(id)
    if (!node) continue
    // dagre reports the centre; LiteGraph node.pos is the top-left corner.
    out.set(id, [node.x - NODE_W / 2, node.y - NODE_H / 2])
  }
  return out
}
