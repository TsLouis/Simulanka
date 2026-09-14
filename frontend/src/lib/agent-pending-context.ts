import './agent-canvas-projection'
import { LGraphCanvas, LiteGraph, type LGraphNode } from 'litegraph.js'
import type { ContextRefDTO } from './api'

const PENDING_COLOR = '#9275c8'

type PendingNode = LGraphNode & {
  simulanka?: { id?: string }
  simulanka_in_ports?: string[]
  simulanka_out_ports?: string[]
  getConnectionPos?: (
    isInput: boolean,
    slot: number,
    out?: Float32Array,
  ) => ArrayLike<number>
}

type PendingLink = {
  simulanka_edge_id?: string
  _pos?: [number, number]
}

type PendingCanvas = LGraphCanvas & {
  ds?: { scale?: number }
}

let nodeRefs = new Set<string>()
let portRefs = new Set<string>()
let edgeRefs = new Set<string>()
let lastKey = ''
const canvases = new Set<LGraphCanvas>()

function refKey(ref: ContextRefDTO): string {
  return `${ref.kind}:${ref.ref_id}`
}

/**
 * Publish the refs that are queued for the next Agent turn.
 *
 * This is deliberately separate from Conversation Projection: pending context is
 * the human saying "look at these", while projection is the Agent saying
 * "look here". Both are draw-time sidecars and neither mutates graph state.
 */
export function setPendingAgentRefs(refs: ContextRefDTO[]): void {
  const normalized: ContextRefDTO[] = []
  const seen = new Set<string>()
  for (const ref of refs) {
    if (
      (ref.kind !== 'node' && ref.kind !== 'edge' && ref.kind !== 'port')
      || !ref.ref_id
    ) continue
    const key = refKey(ref)
    if (seen.has(key)) continue
    seen.add(key)
    normalized.push({ kind: ref.kind, ref_id: ref.ref_id })
  }

  const nextKey = normalized.map(refKey).sort().join('|')
  if (nextKey === lastKey) return
  lastKey = nextKey
  nodeRefs = new Set(normalized.filter(ref => ref.kind === 'node').map(ref => ref.ref_id))
  portRefs = new Set(normalized.filter(ref => ref.kind === 'port').map(ref => ref.ref_id))
  edgeRefs = new Set(normalized.filter(ref => ref.kind === 'edge').map(ref => ref.ref_id))
  for (const canvas of canvases) canvas.setDirty(true, true)
}

function registerCanvas(canvas: LGraphCanvas): void {
  canvases.add(canvas)
}

function connectionPos(
  node: PendingNode,
  isInput: boolean,
  slot: number,
): [number, number] | null {
  if (!node.getConnectionPos) return null
  const position = node.getConnectionPos(isInput, slot)
  if (!position || position.length < 2) return null
  return [Number(position[0]) - node.pos[0], Number(position[1]) - node.pos[1]]
}

function drawPendingNode(
  canvas: PendingCanvas,
  ctx: CanvasRenderingContext2D,
  node: PendingNode,
): void {
  const nodeId = typeof node.simulanka?.id === 'string' ? node.simulanka.id : null
  const nodePending = nodeId !== null && nodeRefs.has(nodeId)
  const inSlots: number[] = []
  const outSlots: number[] = []
  node.simulanka_in_ports?.forEach((portId, index) => {
    if (portRefs.has(portId)) inSlots.push(index)
  })
  node.simulanka_out_ports?.forEach((portId, index) => {
    if (portRefs.has(portId)) outSlots.push(index)
  })
  if (!nodePending && inSlots.length === 0 && outSlots.length === 0) return

  const scale = canvas.ds?.scale ?? 1
  const safeScale = Math.max(scale, 0.35)
  const titleHeight = (LiteGraph as unknown as { NODE_TITLE_HEIGHT?: number }).NODE_TITLE_HEIGHT ?? 30

  if (nodePending) {
    ctx.save()
    ctx.globalAlpha = 0.72
    ctx.strokeStyle = PENDING_COLOR
    ctx.lineWidth = 1.25 / safeScale
    ctx.setLineDash([4 / safeScale, 4 / safeScale])
    ctx.beginPath()
    ctx.roundRect(
      -4 / safeScale,
      -titleHeight - 4 / safeScale,
      node.size[0] + 8 / safeScale,
      node.size[1] + titleHeight + 8 / safeScale,
      5 / safeScale,
    )
    ctx.stroke()
    ctx.restore()
  }

  const drawPort = (isInput: boolean, slot: number) => {
    const pos = connectionPos(node, isInput, slot)
    if (!pos) return
    ctx.save()
    ctx.globalAlpha = 0.8
    ctx.strokeStyle = PENDING_COLOR
    ctx.lineWidth = 1.25 / safeScale
    ctx.setLineDash([3 / safeScale, 3 / safeScale])
    ctx.beginPath()
    ctx.arc(pos[0], pos[1], 9 / safeScale, 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
  }
  for (const slot of inSlots) drawPort(true, slot)
  for (const slot of outSlots) drawPort(false, slot)
}

function drawPendingEdge(
  canvas: PendingCanvas,
  ctx: CanvasRenderingContext2D,
  link: PendingLink,
): void {
  if (!link.simulanka_edge_id || !edgeRefs.has(link.simulanka_edge_id) || !link._pos) return
  const scale = canvas.ds?.scale ?? 1
  const safeScale = Math.max(scale, 0.35)
  const [x, y] = link._pos
  const radius = 7 / safeScale

  ctx.save()
  ctx.globalAlpha = 0.85
  ctx.translate(x, y)
  ctx.rotate(Math.PI / 4)
  ctx.strokeStyle = PENDING_COLOR
  ctx.lineWidth = 1.25 / safeScale
  ctx.setLineDash([3 / safeScale, 3 / safeScale])
  ctx.strokeRect(-radius / 2, -radius / 2, radius, radius)
  ctx.restore()
}

function installPendingContextHooks(): void {
  const proto = LGraphCanvas.prototype as unknown as {
    drawNode: (node: LGraphNode, ctx: CanvasRenderingContext2D) => void
    renderLink: (...args: unknown[]) => void
    simulankaPendingContextInstalled?: boolean
  }
  if (proto.simulankaPendingContextInstalled) return
  proto.simulankaPendingContextInstalled = true

  const baseDrawNode = proto.drawNode
  proto.drawNode = function (
    this: LGraphCanvas,
    node: LGraphNode,
    ctx: CanvasRenderingContext2D,
  ): void {
    registerCanvas(this)
    baseDrawNode.call(this, node, ctx)
    const pendingNode = node as unknown as PendingNode
    if (pendingNode.simulanka) drawPendingNode(this as PendingCanvas, ctx, pendingNode)
  }

  const baseRenderLink = proto.renderLink
  proto.renderLink = function (this: LGraphCanvas, ...args: unknown[]): void {
    registerCanvas(this)
    baseRenderLink.apply(this, args)
    const ctx = args[0] as CanvasRenderingContext2D | undefined
    const link = args[3] as PendingLink | undefined
    if (ctx && link) drawPendingEdge(this as PendingCanvas, ctx, link)
  }
}

installPendingContextHooks()
