import { LGraphCanvas, LiteGraph, type LGraphNode } from 'litegraph.js'
import {
  getConversationProjection,
  subscribeConversationProjection,
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

let projection: ConversationProjection = getConversationProjection()
let nodeRefs = new Set<string>()
let edgeRefs = new Set<string>()
let portRefs = new Set<string>()
const canvases = new Set<LGraphCanvas>()

function rebuildRefSets(next: ConversationProjection): void {
  projection = next
  nodeRefs = new Set(
    next.refs.filter(ref => ref.kind === 'node').map(ref => ref.ref_id),
  )
  edgeRefs = new Set(
    next.refs.filter(ref => ref.kind === 'edge').map(ref => ref.ref_id),
  )
  portRefs = new Set(
    next.refs.filter(ref => ref.kind === 'port').map(ref => ref.ref_id),
  )
}

function registerCanvas(canvas: LGraphCanvas): void {
  canvases.add(canvas)
}

subscribeConversationProjection(next => {
  rebuildRefSets(next)
  for (const canvas of canvases) canvas.setDirty(true, true)
})

function nodeProjection(
  node: ProjectionNode,
): { node: boolean; inPorts: number[]; outPorts: number[] } | null {
  const nodeId = node.simulanka?.id
  const nodePointed = typeof nodeId === 'string' && nodeRefs.has(nodeId)
  const inPorts: number[] = []
  const outPorts: number[] = []
  node.simulanka_in_ports?.forEach((portId, index) => {
    if (portRefs.has(portId)) inPorts.push(index)
  })
  node.simulanka_out_ports?.forEach((portId, index) => {
    if (portRefs.has(portId)) outPorts.push(index)
  })
  return nodePointed || inPorts.length > 0 || outPorts.length > 0
    ? { node: nodePointed, inPorts, outPorts }
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
): void {
  const pos = connectionPos(node, isInput, slot)
  if (!pos) return
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
}

function annotationText(text: string): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > 72 ? `${compact.slice(0, 72)}…` : compact
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

function drawNodeProjection(
  canvas: CanvasWithScale,
  ctx: CanvasRenderingContext2D,
  node: ProjectionNode,
): void {
  const target = nodeProjection(node)
  if (!target) return
  const scale = canvas.ds?.scale ?? 1
  drawNodeHalo(ctx, node, target.node)
  for (const slot of target.inPorts) drawPortTarget(ctx, node, true, slot, scale)
  for (const slot of target.outPorts) drawPortTarget(ctx, node, false, slot, scale)

  // A one-object turn has an unambiguous conversational anchor. Multi-object
  // turns deliberately highlight all refs without pinning prose to one of them.
  if (projection.refs.length === 1 && projection.text) {
    drawAnnotation(
      ctx,
      node.size[0] + 10 / Math.max(scale, 0.45),
      8 / Math.max(scale, 0.45),
      projection.text,
      scale,
    )
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

  if (projection.refs.length === 1 && projection.text) {
    drawAnnotation(
      ctx,
      x + 12 / safeScale,
      y - 16 / safeScale,
      projection.text,
      scale,
    )
  }
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
    // Selection attention may have reduced globalAlpha around the base draw.
    // Agent attention is an independent conversation layer, so restore it.
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
