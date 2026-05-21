// Adapter from Simulanka {nodes, edges, boundary_edges, external_nodes, ports}
// payload → LiteGraph graph. Implements docs/design.md §12.3 (drill-down) and
// §12.4 (boundary-port projection). The adapter is pure rendering: virtual
// boundary nodes never enter graph state.

import { LiteGraph, LGraph, type LGraphNode } from 'litegraph.js'
import type {
  EdgeDTO,
  ExternalNodeDTO,
  GraphPayload,
  NodeDTO,
  PortDTO,
} from './types'

const TYPE_PREFIX = 'simulanka/'
const BOUNDARY_PREFIX = 'simulanka-boundary/'

export interface AdapterCallbacks {
  onDrillDown?: (nodeId: string, nodeName: string) => void
  onJumpExternal?: (externalId: string, externalName: string) => void
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
): AdapterResult {
  const graph = new LGraph()
  const portsById = new Map<string, PortDTO>(payload.ports.map(p => [p.id, p]))

  // Per-port slot lookup. LiteGraph keeps inputs and outputs in separate arrays
  // per node, so each gets its own running index.
  const inSlot = new Map<string, number>()
  const outSlot = new Map<string, number>()
  const byNode = new Map<string, LGraphNode>()

  const cols = Math.max(1, Math.ceil(Math.sqrt(payload.nodes.length)))
  const gridX = (idx: number) => 80 + (idx % cols) * 260
  const gridY = (idx: number) => 80 + Math.floor(idx / cols) * 160

  payload.nodes.forEach((n: NodeDTO, idx: number) => {
    const isContainer = n.child_count > 0
    const lgnode = LiteGraph.createNode(ensureRegistered(n.type)) as LGraphNode
    // The leading marker tells the user a node is drillable; cheap visual hint
    // until we add proper node decoration.
    lgnode.title = isContainer ? `▸ ${n.name}` : n.name
    ;(lgnode as unknown as { simulanka: NodeDTO }).simulanka = n

    let inI = 0
    let outI = 0
    for (const portId of n.ports) {
      const p = portsById.get(portId)
      if (!p) continue
      if (p.side === 'in') {
        lgnode.addInput(p.name, p.port_type || '*')
        inSlot.set(portId, inI++)
      } else {
        lgnode.addOutput(p.name, p.port_type || '*')
        outSlot.set(portId, outI++)
      }
    }

    lgnode.pos = [gridX(idx), gridY(idx)]

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
    connectViaPorts(e, byNode, inSlot, outSlot)
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
      cols,
      callbacks,
    )
  }

  return { graph, byNode }
}

function connectViaPorts(
  e: EdgeDTO,
  byNode: Map<string, LGraphNode>,
  inSlot: Map<string, number>,
  outSlot: Map<string, number>,
): void {
  if (!e.src_port || !e.dst_port) return
  const srcNode = byNode.get(e.src)
  const dstNode = byNode.get(e.dst)
  if (!srcNode || !dstNode) return
  const out = outSlot.get(e.src_port)
  const inp = inSlot.get(e.dst_port)
  if (out === undefined || inp === undefined) return
  srcNode.connect(out, dstNode, inp)
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
  cols: number,
  callbacks: AdapterCallbacks,
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

  // Lay out boundary nodes in columns hugging the canvas edges. Left column
  // for inbound (external → internal), right column for outbound.
  const leftX = -220
  const rightX = 80 + cols * 260 + 40
  let inboundIdx = 0
  let outboundIdx = 0

  for (const bucket of buckets.values()) {
    const lgnode = LiteGraph.createNode(
      ensureRegistered(bucket.direction === 'in' ? 'inbound' : 'outbound', BOUNDARY_PREFIX),
    ) as LGraphNode
    lgnode.title = bucket.direction === 'in'
      ? `← from ${bucket.externalName}`
      : `→ to ${bucket.externalName}`
    ;(lgnode as unknown as { simulanka_boundary: BoundaryBucket }).simulanka_boundary =
      bucket
    // Boundary nodes can't be moved or selected like real nodes — they're a
    // rendering of the subgraph frame. LiteGraph doesn't expose a clean "lock"
    // API; the visual fixed-column placement is enough for MVP.

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
    bucket.edges.forEach((e, i) => {
      if (bucket.direction === 'in') {
        // boundary.out[i] → internal_dst.in[dst_port]
        const dstNode = byNode.get(e.dst)
        if (!dstNode || !e.dst_port) return
        const inp = inSlot.get(e.dst_port)
        if (inp === undefined) return
        lgnode.connect(i, dstNode, inp)
      } else {
        // internal_src.out[src_port] → boundary.in[i]
        const srcNode = byNode.get(e.src)
        if (!srcNode || !e.src_port) return
        const out = outSlot.get(e.src_port)
        if (out === undefined) return
        srcNode.connect(out, lgnode, i)
      }
    })
  }
}
