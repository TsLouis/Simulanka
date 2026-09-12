// Frontend v2 canvas theme. The exported names stay stable so the renderer and
// older components do not need to know that the visual language changed from
// ornate "starlit atlas" to a quiet pixel workspace.
import { LGraphCanvas, LiteGraph, type LGraphNode } from 'litegraph.js'

export const SKY = '#081421'

// Provenance still matters, but it is communicated with a restrained palette.
export const EDGE_COLORS: Record<string, string> = {
  trace: '#68b8f2',
  user: '#e6bf62',
  agent: '#b18af3',
}
export const LINEAGE_COLOR = '#38536e'
export const GHOST_COLOR = '#64778d'
export const REJECTED_GHOST_COLOR = '#ee7b73'
export const VERIFIED_COLOR = '#73d4b1'
export const INFERRED_COLOR = '#64778d'

export const TRUST_COLORS: Record<string, string> = {
  human: '#e6bf62',
  constructed: '#68b8f2',
  reviewed: '#73d4b1',
  checked: '#c7a95a',
  unreviewed: '#64778d',
}

interface NodeStyle {
  color: string
  bgcolor: string
  boxcolor: string
}

const CARD = '#0e1d2d'
const PALETTE_STYLES: Record<string, NodeStyle> = {
  model: { color: '#17243a', bgcolor: CARD, boxcolor: '#e6bf62' },
  module: { color: '#10263a', bgcolor: CARD, boxcolor: '#68b8f2' },
  directory: { color: '#152333', bgcolor: CARD, boxcolor: '#71869f' },
  experiment: { color: '#102b28', bgcolor: CARD, boxcolor: '#73d4b1' },
  run: { color: '#211d3b', bgcolor: CARD, boxcolor: '#b18af3' },
  task: { color: '#2a2417', bgcolor: CARD, boxcolor: '#e6bf62' },
  question: { color: '#132b3f', bgcolor: CARD, boxcolor: '#68b8f2' },
  hypothesis: { color: '#211d3b', bgcolor: CARD, boxcolor: '#b18af3' },
  claim: { color: '#2a2417', bgcolor: CARD, boxcolor: '#e6bf62' },
  evidence: { color: '#102b28', bgcolor: CARD, boxcolor: '#73d4b1' },
  note: { color: '#282515', bgcolor: CARD, boxcolor: '#c7a95a' },
  file: { color: '#162334', bgcolor: CARD, boxcolor: '#71869f' },
  service: { color: '#102b2c', bgcolor: CARD, boxcolor: '#64c8bd' },
}
const NODE_DEFAULT: NodeStyle = { color: '#14243a', bgcolor: CARD, boxcolor: '#71869f' }
const NODE_BOUNDARY: NodeStyle = { color: '#101a28', bgcolor: '#0a1420cc', boxcolor: '#4c6177' }

export function styleNode(node: LGraphNode, paletteToken: string): void {
  const style = paletteToken === 'boundary'
    ? NODE_BOUNDARY
    : (PALETTE_STYLES[paletteToken] ?? NODE_DEFAULT)
  const target = node as unknown as Record<string, unknown>
  target.color = style.color
  target.bgcolor = style.bgcolor
  target.boxcolor = style.boxcolor
}

const CANVAS_FONT = "ui-monospace, 'SFMono-Regular', 'Cascadia Mono', Consolas, monospace"

// ComfyUI-inspired density rule: slots/ports are structural and never disappear.
// Zoom only suppresses labels and card detail. Every input/output keeps its own
// native LiteGraph row, anchor, shape and hit target at every scale.
const DETAIL_MIN_SCALE = 0.98
const DRAFT_LABEL_MIN_SCALE = 0.62

type SlotLike = { label?: string | null }
type SemanticNodeView = { attrs?: Record<string, unknown> }
type DensityNode = LGraphNode & {
  simulanka?: SemanticNodeView
  inputs?: SlotLike[]
  outputs?: SlotLike[]
  onDrawForeground?: (...args: unknown[]) => void
}

type DensityCanvas = LGraphCanvas & {
  ds?: { scale?: number }
  drawNode: (node: LGraphNode, ctx: CanvasRenderingContext2D) => void
}

type DraftLink = {
  simulanka_ghost?: boolean
  _pos?: [number, number]
}

/** Draw a deliberately small, redundant marker for a graph Draft. */
function drawDraftTag(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  compact = false,
): void {
  ctx.save()
  ctx.setLineDash([])
  ctx.font = `600 ${compact ? 7 : 8}px ${CANVAS_FONT}`
  const label = compact ? 'D' : 'DRAFT'
  const width = ctx.measureText(label).width + (compact ? 6 : 10)
  const height = compact ? 11 : 13
  ctx.fillStyle = 'rgba(12, 23, 38, 0.96)'
  ctx.strokeStyle = '#b18af3'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.rect(x - width / 2, y - height / 2, width, height)
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = '#cbb5f7'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, x, y + 0.5)
  ctx.restore()
}

function isDraftNode(node: DensityNode): boolean {
  const attrs = node.simulanka?.attrs
  return attrs?.status === 'proposed' || attrs?.status === 'draft'
}

/**
 * Render-only progressive disclosure for Node/Port density.
 *
 * This follows ComfyUI's mature node-editor convention: slot geometry remains
 * present in low-detail rendering, while labels are omitted. We therefore never
 * remove, merge or overlay ports. The native LiteGraph renderer remains the only
 * source of port position/shape; Simulanka changes only textual/card density.
 */
function installZoomAwareNodeRendering(canvas: LGraphCanvas): void {
  const target = canvas as unknown as DensityCanvas
  const baseDrawNode = target.drawNode.bind(canvas)

  target.drawNode = (node: LGraphNode, ctx: CanvasRenderingContext2D): void => {
    const densityNode = node as unknown as DensityNode
    // Boundary stubs intentionally keep their existing projection rendering.
    if (!densityNode.simulanka) {
      baseDrawNode(node, ctx)
      return
    }

    const scale = target.ds?.scale ?? 1
    const drawDraft = () => {
      if (!isDraftNode(densityNode)) return
      drawDraftTag(ctx, node.size[0] - 24, -13, scale < DETAIL_MIN_SCALE)
    }

    if (scale >= DETAIL_MIN_SCALE) {
      baseDrawNode(node, ctx)
      drawDraft()
      return
    }

    const originalForeground = densityNode.onDrawForeground
    const inputLabels = densityNode.inputs?.map(slot => slot.label)
    const outputLabels = densityNode.outputs?.map(slot => slot.label)

    try {
      // Card/trust details are detail material; node identity and every native
      // port handle remain visible and independently positioned.
      densityNode.onDrawForeground = undefined
      // Non-empty whitespace prevents LiteGraph from falling back to slot.name.
      // This mirrors ComfyUI's low-quality behaviour: keep slot, hide its label.
      densityNode.inputs?.forEach(slot => { slot.label = '\u00a0' })
      densityNode.outputs?.forEach(slot => { slot.label = '\u00a0' })

      baseDrawNode(node, ctx)
      drawDraft()
    } finally {
      densityNode.onDrawForeground = originalForeground
      densityNode.inputs?.forEach((slot, index) => { slot.label = inputLabels?.[index] })
      densityNode.outputs?.forEach((slot, index) => { slot.label = outputLabels?.[index] })
    }
  }
}

/**
 * ComfyUI uses double-click on empty canvas as a primary node-search affordance.
 * Reuse Simulanka's existing persisted add-node path by translating that gesture
 * into the same synthetic contextmenu event already handled by App.svelte.
 * Double-clicking an existing node is left untouched so drill-down keeps working.
 */
function installDoubleClickNodeSearch(canvas: LGraphCanvas): void {
  const target = canvas as unknown as {
    canvas?: HTMLCanvasElement
    graph?: {
      getNodeOnPos?: (x: number, y: number) => LGraphNode | null
    } | null
    convertEventToCanvasOffset?: (event: MouseEvent) => [number, number]
  }
  const element = target.canvas
  if (!element || element.dataset.simulankaNodeSearch === '1') return
  element.dataset.simulankaNodeSearch = '1'

  element.addEventListener('dblclick', event => {
    const pos = target.convertEventToCanvasOffset?.(event)
    if (!pos) return
    const hit = target.graph?.getNodeOnPos?.(pos[0], pos[1]) ?? null
    if (hit) return

    event.preventDefault()
    event.stopPropagation()
    element.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: event.clientX,
      clientY: event.clientY,
      button: 2,
    }))
  })
}

/**
 * Add a tiny DRAFT tag at the center of existing proposed/ghost links. The App
 * already wraps renderLink to add the dashed stroke and continues to own the
 * authoritative accept/verdict actions. Patching the prototype here is useful:
 * App's wrapper captures this decorated renderer and therefore composes with it
 * rather than replacing the marker.
 */
function installDraftLinkMarkers(): void {
  const proto = LGraphCanvas.prototype as unknown as {
    renderLink: (...args: unknown[]) => void
    simulankaDraftMarkerInstalled?: boolean
  }
  if (proto.simulankaDraftMarkerInstalled) return
  proto.simulankaDraftMarkerInstalled = true

  const baseRenderLink = proto.renderLink
  proto.renderLink = function (this: LGraphCanvas, ...args: unknown[]): void {
    baseRenderLink.apply(this, args)
    const ctx = args[0] as CanvasRenderingContext2D | undefined
    const link = args[3] as DraftLink | undefined
    const scale = (this as unknown as { ds?: { scale?: number } }).ds?.scale ?? 1
    if (!ctx || !link?.simulanka_ghost || !link._pos || scale < DRAFT_LABEL_MIN_SCALE) return
    drawDraftTag(ctx, link._pos[0], link._pos[1] - 10, scale < DETAIL_MIN_SCALE)
  }
}

/**
 * Keep the historical function name because App.svelte already calls it.
 * The v2 implementation intentionally removes decorative stars and glow: the
 * graph is the product, not a backdrop. Pixel character comes from crisp lines,
 * small radii and monospace text rather than game-like ornament.
 */
export function applyNightSky(canvas: LGraphCanvas): void {
  const lg = LiteGraph as unknown as Record<string, unknown>
  lg.NODE_TITLE_COLOR = '#edf4ff'
  lg.NODE_SELECTED_TITLE_COLOR = '#ffffff'
  lg.NODE_TEXT_COLOR = '#bfd0e4'
  lg.NODE_DEFAULT_COLOR = '#14243a'
  lg.NODE_DEFAULT_BGCOLOR = CARD
  lg.NODE_DEFAULT_BOXCOLOR = '#71869f'
  lg.NODE_BOX_OUTLINE_COLOR = '#68b8f2'
  lg.WIDGET_BGCOLOR = '#091522'
  lg.LINK_COLOR = LINEAGE_COLOR
  lg.EVENT_LINK_COLOR = '#e6bf62'
  lg.CONNECTING_LINK_COLOR = '#68b8f2'

  const target = canvas as unknown as Record<string, unknown>
  target.background_image = null
  target.show_info = false
  target.clear_background_color = SKY
  target.render_canvas_border = false
  target.render_connections_border = false
  target.default_link_color = LINEAGE_COLOR
  target.title_text_font = `600 12px ${CANVAS_FONT}`
  target.inner_text_font = `normal 10px ${CANVAS_FONT}`
  target.round_radius = 2

  // LiteGraph's native property panel can delete canvas-only nodes. Simulanka
  // keeps all details/actions in its own context UI so graph state stays honest.
  target.onShowNodePanel = () => {}

  installDraftLinkMarkers()
  installZoomAwareNodeRendering(canvas)
  installDoubleClickNodeSearch(canvas)

  const fonts = (document as Document & { fonts?: FontFaceSet }).fonts
  void fonts?.ready.then(() => canvas.setDirty(true, true))
}
