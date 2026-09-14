import { LGraphCanvas, LiteGraph, type LGraphNode } from 'litegraph.js'
import {
  getConversationProjection,
  subscribeConversationProjection,
  type AgentDraftGraphProjection,
  type ConversationProjection,
} from './agent-projection'

const AGENT_COLOR = '#b18af3'
const AGENT_TEXT = '#d7c7fb'
const CANVAS_FONT = "ui-monospace, 'SFMono-Regular', 'Cascadia Mono', Consolas, monospace"
const ANNOTATION_MIN_SCALE = 0.45

type ProjectionNode = LGraphNode & {
  simulanka?: { id?: string }
  simulanka_in_ports?: string[]
  simulanka_out_ports?: string[]
  getConnectionPos?: (
    isInput: boolean,
    slot: number,
    out?: Float32Array,
  ) => ArrayLike<number>
}

type ProjectionLink = {
  simulanka_edge_id?: string
  _pos?: [number, number]
}

type CanvasWithScale = LGraphCanvas & {
  ds?: { scale?: number }
}

type RefKey = string

let projection: ConversationProjection = getConversationProjection()
let nodeRefs = new Set<string>()
let edgeRefs = new Set<string>()
let portRefs = new Set<string>()
let annotations = new Map<RefKey, string>()
let attentionLabels = new Map<RefKey, string>()
let draftGraphs = new Map<RefKey, AgentDraftGraphProjection[]>()
const canvases = new Set<LGraphCanvas>()

function refKey(kind: string, refId: string): RefKey {
  return `${kind}:${refId}`
}

function addRef(kind: 'node' | 'edge' | 'port', refId: string): void {
  if (kind === 'node') nodeRefs.add(refId)
  else if (kind === 'edge') edgeRefs.add(refId)
  else portRefs.add(refId)
}

function rebuildProjectionState(next: ConversationProjection): void {
  projection = next
  nodeRefs = new Set()
  edgeRefs = new Set()
  portRefs = new Set()
  annotations = new Map()
  attentionLabels = new Map()
  draftGraphs = new Map()

  // Backward-compatible conversation projection: before structured visual
  // output exists, the exact refs delivered to the Agent are the only safe
  // things it can visibly point back at.
  if (next.visuals.length === 0) {
    for (const ref of next.refs) addRef(ref.kind, ref.ref_id)
    return
  }

  for (const visual of next.visuals) {
    if (visual.kind === 'attention') {
      for (const ref of visual.refs) {
        addRef(ref.kind, ref.ref_id)
        if (visual.label) attentionLabels.set(refKey(ref.kind, ref.ref_id), visual.label)
      }
      continue
    }
    if (visual.kind === 'annotation') {
      addRef(visual.target.kind, visual.target.ref_id)
      annotations.set(refKey(visual.target.kind, visual.target.ref_id), visual.text)
      continue
    }
    addRef(visual.anchor.kind, visual.anchor.ref_id)
    const key = refKey(visual.anchor.kind, visual.anchor.ref_id)
    draftGraphs.set(key, [...(draftGraphs.get(key) ?? []), visual])
  }
}

function registerCanvas(canvas: LGraphCanvas): void {
  canvases.add(canvas)
}

subscribeConversationProjection(next => {
  rebuildProjectionState(next)
  for (const canvas of canvases) canvas.setDirty(true, true)
})

function nodeProjection(
  node: ProjectionNode,
): { node: boolean; nodeId: string | null; inPorts: number[]; outPorts: number[] } | null {
  const nodeId = typeof node.simulanka?.id === 'string' ? node.simulanka.id : null
  const nodePointed = nodeId !== null && nodeRefs.has(nodeId)
  const inPorts: number[] = []
  const outPorts: number[] = []
  node.simulanka_in_ports?.forEach((portId, index) => {
    if (portRefs.has(portId)) inPorts.push(index)
  })
  node.simulanka_out_ports?.forEach((portId, index) => {
    if (portRefs.has(portId)) outPorts.push(index)
  })
  return nodePointed || inPorts.length > 0 || outPorts.length > 0
    ? { node: nodePointed, nodeId, inPorts, outPorts }
    : null
}

function drawNodeHalo(
  ctx: CanvasRenderingContext2D,
  node: LGraphNode,
  strong: boolean,
): void {
  const titleHeight = (LiteGraph as unknown as { NODE_TITLE_HEIGHT?: number }).NODE_TITLE_HEIGHT ?? 30
  ctx.save()
  ctx.globalAlpha = strong ? 0.94 : 0.52
  ctx.strokeStyle = AGENT_COLOR
  ctx.lineWidth = strong ? 2 : 1.25
  ctx.setLineDash(strong ? [] : [4, 4])
  ctx.shadowColor = AGENT_COLOR
  ctx.shadowBlur = strong ? 7 : 3
  ctx.beginPath()
  ctx.roundRect(
    -3,
    -titleHeight - 3,
    node.size[0] + 6,
    node.size[1] + titleHeight + 6,
    5,
  )
  ctx.stroke()
  ctx.restore()
}

function connectionPos(
  node: ProjectionNode,
  isInput: boolean,
  slot: number,
): [number, number] | null {
  const getPos = node.getConnectionPos
  if (!getPos) return null
  const position = getPos.call(node, isInput, slot)
  if (!position || position.length < 2) return null
  return [Number(position[0]) - node.pos[0], Number(position[1]) - node.pos[1]]
}

function drawPortTarget(
  ctx: CanvasRenderingContext2D,
  node: ProjectionNode,
  isInput: boolean,
  slot: number,
  scale: number,
): [number, number] | null {
  const pos = connectionPos(node, isInput, slot)
  if (!pos) return null
  const safeScale = Math.max(scale, 0.35)
  const radius = 8 / safeScale
  ctx.save()
  ctx.globalAlpha = 1
  ctx.strokeStyle = AGENT_COLOR
  ctx.fillStyle = 'rgba(177, 138, 243, 0.12)'
  ctx.lineWidth = 1.5 / safeScale
  ctx.beginPath()
  ctx.arc(pos[0], pos[1], radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.stroke()
  ctx.restore()
  return pos
}

function annotationText(text: string): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > 88 ? `${compact.slice(0, 88)}…` : compact
}

function draftText(text: string): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > 26 ? `${compact.slice(0, 26)}…` : compact
}

function drawAnnotation(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  text: string,
  scale: number,
): void {
  if (scale < ANNOTATION_MIN_SCALE) return
  const safeScale = Math.max(scale, ANNOTATION_MIN_SCALE)
  const fontSize = 10 / safeScale
  const padX = 7 / safeScale
  const padY = 5 / safeScale
  const label = annotationText(text)

  ctx.save()
  ctx.globalAlpha = 1
  ctx.setLineDash([])
  ctx.font = `500 ${fontSize}px ${CANVAS_FONT}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  const width = ctx.measureText(label).width + padX * 2
  const height = fontSize + padY * 2
  ctx.fillStyle = 'rgba(12, 23, 38, 0.96)'
  ctx.strokeStyle = AGENT_COLOR
  ctx.lineWidth = 1 / safeScale
  ctx.beginPath()
  ctx.roundRect(x, y - height / 2, width, height, 3 / safeScale)
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = AGENT_TEXT
  ctx.fillText(label, x + padX, y)
  ctx.restore()
}

function drawArrowHead(
  ctx: CanvasRenderingContext2D,
  sx: number,
  sy: number,
  dx: number,
  dy: number,
  size: number,
): void {
  const angle = Math.atan2(dy - sy, dx - sx)
  ctx.beginPath()
  ctx.moveTo(dx, dy)
  ctx.lineTo(
    dx - size * Math.cos(angle - 0.5),
    dy - size * Math.sin(angle - 0.5),
  )
  ctx.lineTo(
    dx - size * Math.cos(angle + 0.5),
    dy - size * Math.sin(angle + 0.5),
  )
  ctx.closePath()
  ctx.fill()
}

function drawDraftGraph(
  ctx: CanvasRenderingContext2D,
  projection: AgentDraftGraphProjection,
  anchorX: number,
  anchorY: number,
  scale: number,
  stackIndex = 0,
): void {
  if (scale < ANNOTATION_MIN_SCALE) return
  const safeScale = Math.max(scale, ANNOTATION_MIN_SCALE)
  const boxW = 92 / safeScale
  const boxH = 30 / safeScale
  const gapX = 28 / safeScale
  const gapY = 18 / safeScale
  const stackOffset = stackIndex * 150 / safeScale
  const startX = anchorX + 24 / safeScale
  const startY = anchorY + 42 / safeScale + stackOffset
  const cols = Math.max(1, Math.min(3, projection.nodes.length))
  const rows = Math.max(1, Math.ceil(projection.nodes.length / 3))
  const panelPadX = 10 / safeScale
  const panelTop = 20 / safeScale
  const panelX = startX - panelPadX
  const panelY = startY - panelTop
  const panelW = cols * boxW + Math.max(0, cols - 1) * gapX + panelPadX * 2
  const panelH = rows * boxH + Math.max(0, rows - 1) * gapY + 38 / safeScale
  const positions = new Map<string, [number, number]>()

  projection.nodes.forEach((node, index) => {
    const col = index % 3
    const row = Math.floor(index / 3)
    positions.set(node.id, [
      startX + col * (boxW + gapX),
      startY + row * (boxH + gapY),
    ])
  })

  ctx.save()
  ctx.globalAlpha = 0.9
  ctx.lineWidth = 1 / safeScale

  // The whole sketch reads as one temporary idea, visually tethered to the real
  // graph object that prompted it. This leader is explanatory only; it is not a
  // semantic Edge and never participates in hit-testing or persistence.
  ctx.strokeStyle = 'rgba(177, 138, 243, 0.62)'
  ctx.setLineDash([3 / safeScale, 4 / safeScale])
  ctx.beginPath()
  ctx.moveTo(anchorX, anchorY)
  ctx.lineTo(panelX, panelY + 13 / safeScale)
  ctx.stroke()

  ctx.fillStyle = 'rgba(25, 22, 48, 0.28)'
  ctx.strokeStyle = 'rgba(177, 138, 243, 0.72)'
  ctx.beginPath()
  ctx.roundRect(panelX, panelY, panelW, panelH, 4 / safeScale)
  ctx.fill()
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = AGENT_COLOR
  ctx.font = `700 ${7 / safeScale}px ${CANVAS_FONT}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('DRAFT', panelX + 7 / safeScale, panelY + 9 / safeScale)

  ctx.strokeStyle = AGENT_COLOR
  ctx.fillStyle = AGENT_COLOR
  ctx.font = `500 ${9 / safeScale}px ${CANVAS_FONT}`
  ctx.textAlign = 'center'

  for (const edge of projection.edges) {
    const src = positions.get(edge.src)
    const dst = positions.get(edge.dst)
    if (!src || !dst) continue
    const sx = src[0] + boxW / 2
    const sy = src[1] + boxH / 2
    const dx = dst[0] + boxW / 2
    const dy = dst[1] + boxH / 2
    ctx.setLineDash([5 / safeScale, 4 / safeScale])
    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.lineTo(dx, dy)
    ctx.stroke()
    ctx.setLineDash([])
    drawArrowHead(ctx, sx, sy, dx, dy, 6 / safeScale)
    if (edge.label) {
      ctx.fillStyle = AGENT_TEXT
      ctx.fillText(draftText(edge.label), (sx + dx) / 2, (sy + dy) / 2 - 8 / safeScale)
      ctx.fillStyle = AGENT_COLOR
    }
  }

  for (const node of projection.nodes) {
    const pos = positions.get(node.id)
    if (!pos) continue
    const [x, y] = pos
    ctx.setLineDash([4 / safeScale, 3 / safeScale])
    ctx.fillStyle = 'rgba(25, 22, 48, 0.90)'
    ctx.strokeStyle = AGENT_COLOR
    ctx.beginPath()
    ctx.roundRect(x, y, boxW, boxH, 3 / safeScale)
    ctx.fill()
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = AGENT_TEXT
    ctx.fillText(draftText(node.label), x + boxW / 2, y + boxH / 2)
    if (node.type) {
      ctx.globalAlpha = 0.66
      ctx.font = `500 ${7 / safeScale}px ${CANVAS_FONT}`
      ctx.fillText(draftText(node.type), x + boxW / 2, y + boxH + 7 / safeScale)
      ctx.font = `500 ${9 / safeScale}px ${CANVAS_FONT}`
      ctx.globalAlpha = 0.9
    }
  }
  ctx.restore()
}

function annotationFor(kind: string, refId: string): string | null {
  const key = refKey(kind, refId)
  return annotations.get(key) ?? attentionLabels.get(key) ?? null
}

function draftGraphsFor(kind: string, refId: string): AgentDraftGraphProjection[] {
  return draftGraphs.get(refKey(kind, refId)) ?? []
}

function drawNodeProjection(
  canvas: CanvasWithScale,
  ctx: CanvasRenderingContext2D,
  node: ProjectionNode,
): void {
  const target = nodeProjection(node)
  if (!target) return
  const scale = canvas.ds?.scale ?? 1
  drawNodeHalo(ctx, node, target.node)

  if (target.node && target.nodeId) {
    const label = annotationFor('node', target.nodeId)
      ?? (projection.visuals.length === 0 && projection.refs.length === 1 ? projection.text : null)
    if (label) {
      drawAnnotation(
        ctx,
        node.size[0] + 10 / Math.max(scale, 0.45),
        8 / Math.max(scale, 0.45),
        label,
        scale,
      )
    }
    draftGraphsFor('node', target.nodeId).forEach((draft, index) => {
      drawDraftGraph(ctx, draft, node.size[0], 0, scale, index)
    })
  }

  for (const slot of target.inPorts) {
    const pos = drawPortTarget(ctx, node, true, slot, scale)
    const portId = node.simulanka_in_ports?.[slot]
    if (!pos || !portId) continue
    const label = annotationFor('port', portId)
      ?? (projection.visuals.length === 0 && projection.refs.length === 1 ? projection.text : null)
    if (label) drawAnnotation(ctx, pos[0] + 12 / Math.max(scale, 0.45), pos[1], label, scale)
    draftGraphsFor('port', portId).forEach((draft, index) => {
      drawDraftGraph(ctx, draft, pos[0], pos[1], scale, index)
    })
  }

  for (const slot of target.outPorts) {
    const pos = drawPortTarget(ctx, node, false, slot, scale)
    const portId = node.simulanka_out_ports?.[slot]
    if (!pos || !portId) continue
    const label = annotationFor('port', portId)
      ?? (projection.visuals.length === 0 && projection.refs.length === 1 ? projection.text : null)
    if (label) drawAnnotation(ctx, pos[0] + 12 / Math.max(scale, 0.45), pos[1], label, scale)
    draftGraphsFor('port', portId).forEach((draft, index) => {
      drawDraftGraph(ctx, draft, pos[0], pos[1], scale, index)
    })
  }
}

function drawEdgeProjection(
  canvas: CanvasWithScale,
  ctx: CanvasRenderingContext2D,
  link: ProjectionLink,
): void {
  const edgeId = link.simulanka_edge_id
  if (!edgeId || !edgeRefs.has(edgeId) || !link._pos) return
  const scale = canvas.ds?.scale ?? 1
  const safeScale = Math.max(scale, 0.35)
  const [x, y] = link._pos

  ctx.save()
  ctx.globalAlpha = 1
  ctx.setLineDash([])
  ctx.fillStyle = AGENT_COLOR
  ctx.strokeStyle = 'rgba(8, 20, 33, 0.94)'
  ctx.lineWidth = 2 / safeScale
  ctx.font = `700 ${12 / safeScale}px ${CANVAS_FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.strokeText('✦', x, y)
  ctx.fillText('✦', x, y)
  ctx.restore()

  const label = annotationFor('edge', edgeId)
    ?? (projection.visuals.length === 0 && projection.refs.length === 1 ? projection.text : null)
  if (label) drawAnnotation(ctx, x + 12 / safeScale, y - 16 / safeScale, label, scale)
  draftGraphsFor('edge', edgeId).forEach((draft, index) => {
    drawDraftGraph(ctx, draft, x, y, scale, index)
  })
}

function installPrototypeProjectionHooks(): void {
  const proto = LGraphCanvas.prototype as unknown as {
    drawNode: (node: LGraphNode, ctx: CanvasRenderingContext2D) => void
    renderLink: (...args: unknown[]) => void
    simulankaAgentProjectionInstalled?: boolean
  }
  if (proto.simulankaAgentProjectionInstalled) return
  proto.simulankaAgentProjectionInstalled = true

  const baseDrawNode = proto.drawNode
  proto.drawNode = function (
    this: LGraphCanvas,
    node: LGraphNode,
    ctx: CanvasRenderingContext2D,
  ): void {
    registerCanvas(this)
    baseDrawNode.call(this, node, ctx)
    const projectionNode = node as unknown as ProjectionNode
    if (!projectionNode.simulanka) return
    drawNodeProjection(this as CanvasWithScale, ctx, projectionNode)
  }

  const baseRenderLink = proto.renderLink
  proto.renderLink = function (this: LGraphCanvas, ...args: unknown[]): void {
    registerCanvas(this)
    baseRenderLink.apply(this, args)
    const ctx = args[0] as CanvasRenderingContext2D | undefined
    const link = args[3] as ProjectionLink | undefined
    if (ctx && link) drawEdgeProjection(this as CanvasWithScale, ctx, link)
  }
}

installPrototypeProjectionHooks()
