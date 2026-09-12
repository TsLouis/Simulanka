// Adapter from Simulanka {nodes, edges, boundary_edges, external_nodes, ports}
// payload → LiteGraph graph. Implements docs/design.md §12.3 (drill-down) and
// §12.4 (boundary-port projection). The adapter is pure rendering: virtual
// boundary nodes never enter graph state.

import dagre from 'dagre'
import { LiteGraph, LGraph, type LGraphNode } from 'litegraph.js'
import { CARD_LINE_H, CARD_WIDTH, cardLines, type CardLine } from './cards'
import { edgeConnectionRejection } from './edge-rules'
import { resolveNodePresentation } from './presentation'
import {
  EDGE_COLORS,
  GHOST_COLOR,
  INFERRED_COLOR,
  REJECTED_GHOST_COLOR,
  styleNode,
  TRUST_COLORS,
  VERIFIED_COLOR,
} from './theme'
import type {
  EdgeDTO,
  ExternalNodeDTO,
  GraphPayload,
  NodeDTO,
  PortDTO,
  RegistryDescriptorDTO,
  ShapeCheck,
  TrustLevel,
} from './types'

interface LiteLink {
  id: number
  origin_id: number
  origin_slot: number
  target_id: number
  target_slot: number
  simulanka_edge_id?: string
  simulanka_ghost?: boolean
  simulanka_slice?: string
  color?: string
}

const TYPE_PREFIX = 'simulanka/'
const BOUNDARY_PREFIX = 'simulanka-boundary/'
const NODE_W = 200
const NODE_H = 100

export interface AdapterCallbacks {
  onDrillDown?: (nodeId: string, nodeName: string) => void
  onJumpExternal?: (externalId: string, externalName: string) => void
  onCreateEdge?: (
    srcPortId: string,
    dstPortId: string,
    shapeCheck: ShapeCheck,
  ) => Promise<boolean>
  onDeleteEdge?: (edgeId: string) => void
  onConnectionRejected?: (reason: string) => void
}

export interface LineageEdge {
  src: LGraphNode
  dst: LGraphNode
  type: string
}

export interface AdapterResult {
  graph: LGraph
  byNode: Map<string, LGraphNode>
  lineage: LineageEdge[]
}

function ensureRegistered(typeName: string, prefix: string = TYPE_PREFIX): string {
  const full = prefix + typeName
  if (LiteGraph.registered_node_types[full]) return full
  function NodeCtor(this: LGraphNode) {}
  const meta = NodeCtor as unknown as { title: string; collapsable?: boolean }
  meta.title = typeName
  // LiteGraph's native collapsed state compresses all slots into the title
  // silhouette. That is fine for workflow nodes but wrong for Simulanka:
  // independent Ports are semantic topology and must never visually merge.
  // Keep boundary projections on LiteGraph defaults; only real semantic nodes
  // opt out of collapse. Detail density is handled by zoom instead.
  if (prefix === TYPE_PREFIX) meta.collapsable = false
  LiteGraph.registerNodeType(full, NodeCtor as unknown as new () => LGraphNode)
  return full
}

export function buildLiteGraph(
  payload: GraphPayload,
  callbacks: AdapterCallbacks = {},
  persistedPositions: Record<string, [number, number]> = {},
  descriptor: RegistryDescriptorDTO | null = null,
): AdapterResult {
  const graph = new LGraph()
  const portsById = new Map<string, PortDTO>(payload.ports.map(p => [p.id, p]))

  const inSlot = new Map<string, number>()
  const outSlot = new Map<string, number>()
  const byNode = new Map<string, LGraphNode>()

  let building = true
  const INPUT = (LiteGraph as unknown as { INPUT: number }).INPUT

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

  function onConnectInput(
    this: LGraphNode,
    inputIndex: number,
    _outputType: unknown,
    _outputSlot: unknown,
    outputNode: LGraphNode,
    outputIndex: number,
  ): boolean {
    if (building) return true
    const source = (outputNode as unknown as { simulanka?: NodeDTO }).simulanka
    const target = (this as unknown as { simulanka?: NodeDTO }).simulanka
    const sourcePortId = (outputNode as unknown as { simulanka_out_ports?: string[] })
      .simulanka_out_ports?.[outputIndex]
    const targetPortId = (this as unknown as { simulanka_in_ports?: string[] })
      .simulanka_in_ports?.[inputIndex]
    const sourcePort = sourcePortId ? portsById.get(sourcePortId) : undefined
    const targetPort = targetPortId ? portsById.get(targetPortId) : undefined
    if (!source || !target || !sourcePort || !targetPort) {
      callbacks.onConnectionRejected?.('边界投影端点不可直接连接')
      return false
    }
    const rejection = edgeConnectionRejection(
      descriptor,
      'data_flow',
      source,
      target,
      sourcePort,
      targetPort,
    )
    if (rejection) callbacks.onConnectionRejected?.(rejection)
    return rejection === null
  }

  function onConnectOutput(
    _outputIndex: number,
    _inputType: unknown,
    _inputSlot: unknown,
    inputNode: LGraphNode,
  ): boolean {
    if (building) return true
    if ((inputNode as unknown as { simulanka?: NodeDTO }).simulanka) return true
    callbacks.onConnectionRejected?.('边界投影端点不可直接连接')
    return false
  }

  const autoPos = computeAutoLayout(payload, descriptor)

  payload.nodes.forEach((n: NodeDTO) => {
    const isContainer = n.child_count > 0
    const presentation = resolveNodePresentation(descriptor, n.type)
    const lgnode = LiteGraph.createNode(ensureRegistered(n.type)) as LGraphNode
    lgnode.title = isContainer ? `▸ ${n.name}` : n.name
    styleNode(lgnode, presentation?.palette_token ?? 'default')
    ;(lgnode as unknown as { simulanka: NodeDTO }).simulanka = n

    let inI = 0
    let outI = 0
    const inPorts: string[] = []
    const outPorts: string[] = []
    for (const portId of n.ports) {
      const p = portsById.get(portId)
      if (!p) continue
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
    ;(lgnode as unknown as { onConnectInput: typeof onConnectInput }).onConnectInput = onConnectInput
    ;(lgnode as unknown as { onConnectOutput: typeof onConnectOutput }).onConnectOutput = onConnectOutput

    const card = cardLines(n, presentation)
    if (card.length > 0 || n.trust) attachCard(lgnode, card, n.trust)

    const pos = persistedPositions[n.id] ?? autoPos.get(n.id) ?? [80, 80]
    lgnode.pos = [pos[0], pos[1]]

    if (callbacks.onDrillDown) {
      const cb = callbacks.onDrillDown
      ;(lgnode as unknown as { onDblClick: () => void }).onDblClick = () => {
        cb(n.id, n.name)
      }
    }

    graph.add(lgnode)
    byNode.set(n.id, lgnode)
  })

  const lineage: LineageEdge[] = []
  for (const e of payload.edges) {
    const link = connectViaPorts(e, byNode, inSlot, outSlot)
    if (link) {
      decorateLink(link, e)
    } else if (e.type !== 'contains') {
      const src = byNode.get(e.src)
      const dst = byNode.get(e.dst)
      if (src && dst) lineage.push({ src, dst, type: e.type })
    }
  }

  if (payload.root !== null) {
    injectBoundary(graph, payload, byNode, inSlot, outSlot, portsById, onConnectionsChange, callbacks)
  }

  building = false
  return { graph, byNode, lineage }
}

interface CardStash {
  lines: CardLine[]
  top: number
  trust: TrustLevel | null
}

function attachCard(
  lgnode: LGraphNode,
  lines: CardLine[],
  trust: TrustLevel | null,
): void {
  const base = lgnode.computeSize()
  const top = base[1] + 6
  if (lines.length > 0) {
    lgnode.size = [Math.max(base[0], CARD_WIDTH), top + lines.length * CARD_LINE_H + 8]
  }
  ;(lgnode as unknown as { simulanka_card: CardStash }).simulanka_card = {
    lines,
    top,
    trust,
  }
  ;(lgnode as unknown as {
    onDrawForeground: (ctx: CanvasRenderingContext2D) => void
  }).onDrawForeground = drawCardForeground
}

function drawTrustRing(
  ctx: CanvasRenderingContext2D,
  size: [number, number] | Float32Array,
  trust: TrustLevel,
): void {
  const color = TRUST_COLORS[trust]
  if (!color) return
  const titleH = (LiteGraph as unknown as { NODE_TITLE_HEIGHT: number }).NODE_TITLE_HEIGHT
  ctx.save()
  ctx.beginPath()
  ctx.roundRect(-1.5, -titleH - 1.5, size[0] + 3, size[1] + titleH + 3, 8)
  ctx.strokeStyle = color
  ctx.globalAlpha = trust === 'unreviewed' ? 0.3 : 0.8
  ctx.lineWidth = 1.5
  if (trust !== 'unreviewed') {
    ctx.shadowColor = color
    ctx.shadowBlur = 6
  }
  ctx.stroke()
  ctx.restore()
}

function drawCardForeground(this: LGraphNode, ctx: CanvasRenderingContext2D): void {
  const self = this as unknown as {
    simulanka_card?: CardStash
    flags?: { collapsed?: boolean }
  }
  const stash = self.simulanka_card
  if (!stash || self.flags?.collapsed) return
  if (stash.trust) drawTrustRing(ctx, this.size, stash.trust)
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
  if (typeof e.attrs.output_slice === 'string') {
    link.simulanka_slice = e.attrs.output_slice
  }
}

function computeShapeCheck(src?: PortDTO, dst?: PortDTO): ShapeCheck {
  if (!src || !dst) return 'unknown'
  const ss = Array.isArray(src.attrs.shape) ? (src.attrs.shape as number[]) : null
  const ds = Array.isArray(dst.attrs.shape) ? (dst.attrs.shape as number[]) : null
  if (!ss || !ds || src.attrs.confidence !== 'verified' || dst.attrs.confidence !== 'verified') {
    return 'unknown'
  }
  return ss.length === ds.length && ss.every((v, i) => v === ds[i]) ? 'match' : 'mismatch'
}

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
  direction: 'in' | 'out'
  edges: EdgeDTO[]
}

function injectBoundary(
  graph: LGraph,
  payload: GraphPayload,
  byNode: Map<string, LGraphNode>,
  inSlot: Map<string, number>,
  outSlot: Map<string, number>,
  portsById: Map<string, PortDTO>,
  onConnectionsChange: (
    this: LGraphNode,
    type: number,
    slot: number,
    connected: boolean,
    link: LiteLink | undefined,
  ) => void,
  callbacks: AdapterCallbacks,
): void {
  const rootId = payload.root as string
  const rootName = payload.root_info?.name ?? rootId
  const externalById = new Map<string, ExternalNodeDTO>(
    payload.external_nodes.map(x => [x.id, x]),
  )

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

  const bracketSlots = new Map<string, { node: LGraphNode; slot: number }>()
  const rootPorts = payload.ports.filter(p => p.node_id === rootId)
  const rootType = payload.root_info?.type ?? ''
  const alwaysBracket = rootType === 'model' || rootType === 'module'
  let inboundY = 80
  let outboundY = 80
  const mkBracket = (title: string, ports: PortDTO[], side: 'in' | 'out'): void => {
    if (ports.length === 0 && !alwaysBracket) return
    const node = LiteGraph.createNode(
      ensureRegistered(side === 'in' ? 'inputs' : 'outputs', BOUNDARY_PREFIX),
    ) as LGraphNode
    node.title = title
    styleNode(node, 'boundary')
    ;(node as unknown as { onConnectionsChange: typeof onConnectionsChange })
      .onConnectionsChange = onConnectionsChange
    const slotIds: string[] = []
    ports.forEach((p, i) => {
      if (side === 'in') node.addOutput(p.name, p.port_type || '*', slotExtra(p))
      else node.addInput(p.name, p.port_type || '*', slotExtra(p))
      bracketSlots.set(p.id, { node, slot: i })
      slotIds[i] = p.id
    })
    if (side === 'in') {
      ;(node as unknown as { simulanka_out_ports: string[] }).simulanka_out_ports = slotIds
    } else {
      ;(node as unknown as { simulanka_in_ports: string[] }).simulanka_in_ports = slotIds
    }
    node.size = node.computeSize()
    if (side === 'in') {
      node.pos = [leftX, inboundY]
      inboundY += node.size[1] + 50
    } else {
      node.pos = [rightX, outboundY]
      outboundY += node.size[1] + 50
    }
    graph.add(node)
  }
  mkBracket(`▷ ${rootName} 输入`, rootPorts.filter(p => p.side === 'in'), 'in')
  mkBracket(`${rootName} 输出 ▷`, rootPorts.filter(p => p.side === 'out'), 'out')

  const buckets = new Map<string, BoundaryBucket>()
  for (const e of payload.boundary_edges) {
    if (!e.src_port || !e.dst_port) continue
    const srcInside = byNode.has(e.src)
    const dstInside = byNode.has(e.dst)
    if (srcInside === dstInside) continue
    const externalId = srcInside ? e.dst : e.src

    if (externalId === rootId) {
      const outsidePort = srcInside ? e.dst_port : e.src_port
      const bs = bracketSlots.get(outsidePort)
      if (bs) {
        let link: LiteLink | null = null
        if (srcInside) {
          const srcNode = byNode.get(e.src)
          const out = outSlot.get(e.src_port)
          if (srcNode && out !== undefined) {
            link = srcNode.connect(out, bs.node, bs.slot) as unknown as LiteLink | null
          }
        } else {
          const dstNode = byNode.get(e.dst)
          const inp = inSlot.get(e.dst_port)
          if (dstNode && inp !== undefined) {
            link = bs.node.connect(bs.slot, dstNode, inp) as unknown as LiteLink | null
          }
        }
        if (link) decorateLink(link, e)
        continue
      }
    }

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
    ;(lgnode as unknown as { onConnectionsChange: typeof onConnectionsChange })
      .onConnectionsChange = onConnectionsChange

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

    lgnode.size = lgnode.computeSize()
    if (bucket.direction === 'in') {
      lgnode.pos = [leftX, inboundY]
      inboundY += lgnode.size[1] + 50
    } else {
      lgnode.pos = [rightX, outboundY]
      outboundY += lgnode.size[1] + 50
    }

    if (callbacks.onJumpExternal) {
      const cb = callbacks.onJumpExternal
      const { externalId, externalName } = bucket
      ;(lgnode as unknown as { onDblClick: () => void }).onDblClick = () => {
        cb(externalId, externalName)
      }
    }

    graph.add(lgnode)

    bucket.edges.forEach((e, i) => {
      let link: LiteLink | null = null
      if (bucket.direction === 'in') {
        const dstNode = byNode.get(e.dst)
        if (!dstNode || !e.dst_port) return
        const inp = inSlot.get(e.dst_port)
        if (inp === undefined) return
        link = lgnode.connect(i, dstNode, inp) as unknown as LiteLink | null
      } else {
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

function computeAutoLayout(
  payload: GraphPayload,
  descriptor: RegistryDescriptorDTO | null,
): Map<string, [number, number]> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90, marginx: 40, marginy: 40 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const n of payload.nodes) {
    g.setNode(n.id, {
      width: NODE_W,
      height: NODE_H
        + cardLines(n, resolveNodePresentation(descriptor, n.type)).length * CARD_LINE_H,
    })
  }
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
    out.set(id, [node.x - NODE_W / 2, node.y - NODE_H / 2])
  }
  return out
}
