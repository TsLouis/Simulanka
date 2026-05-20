// Adapter from Simulanka {nodes, edges, ports} payload → LiteGraph graph.
// MVP: flat single-level render with auto-positioned nodes.
// Known gaps (deferred): hierarchical nesting, double-click drill-down,
// boundary-port projection for cross-level edges, edges without ports
// (contains/supports/etc.) are skipped — they have no slot to attach to.

import { LiteGraph, LGraph, type LGraphNode } from 'litegraph.js'
import type { GraphPayload, NodeDTO, PortDTO } from './types'

const TYPE_PREFIX = 'simulanka/'

function ensureRegistered(typeName: string): string {
  const full = TYPE_PREFIX + typeName
  if (LiteGraph.registered_node_types[full]) return full
  // Bare ctor; per-instance slots are added after createNode().
  function NodeCtor(this: LGraphNode) {}
  ;(NodeCtor as unknown as { title: string }).title = typeName
  LiteGraph.registerNodeType(full, NodeCtor as unknown as new () => LGraphNode)
  return full
}

export interface AdapterResult {
  graph: LGraph
  byNode: Map<string, LGraphNode>
}

export function buildLiteGraph(payload: GraphPayload): AdapterResult {
  const graph = new LGraph()
  const portsById = new Map<string, PortDTO>(payload.ports.map(p => [p.id, p]))

  // Per-node port-id → slot-index maps (in/out tracked separately because
  // LiteGraph uses two distinct slot lists per node).
  const inSlot = new Map<string, number>()
  const outSlot = new Map<string, number>()
  const byNode = new Map<string, LGraphNode>()

  payload.nodes.forEach((n: NodeDTO, idx: number) => {
    const lgnode = LiteGraph.createNode(ensureRegistered(n.type)) as LGraphNode
    lgnode.title = n.name
    // Stash original DTO for later inspection / future drill-down hook.
    ;(lgnode as unknown as { simulanka: NodeDTO }).simulanka = n

    // Add slots in port order. Inputs/outputs are separate arrays in LiteGraph
    // so each gets its own running index.
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

    // Crude grid layout. Replaced later when we introduce real layout (dagre etc.).
    const cols = Math.max(1, Math.ceil(Math.sqrt(payload.nodes.length)))
    const col = idx % cols
    const row = Math.floor(idx / cols)
    lgnode.pos = [80 + col * 260, 80 + row * 160]

    graph.add(lgnode)
    byNode.set(n.id, lgnode)
  })

  // Connect edges that have port endpoints; skip structural edges in this MVP.
  for (const e of payload.edges) {
    if (!e.src_port || !e.dst_port) continue
    const srcNode = byNode.get(e.src)
    const dstNode = byNode.get(e.dst)
    if (!srcNode || !dstNode) continue
    const out = outSlot.get(e.src_port)
    const inp = inSlot.get(e.dst_port)
    if (out === undefined || inp === undefined) continue
    srcNode.connect(out, dstNode, inp)
  }

  return { graph, byNode }
}
