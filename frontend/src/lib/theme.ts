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

  const fonts = (document as Document & { fonts?: FontFaceSet }).fonts
  void fonts?.ready.then(() => canvas.setDirty(true, true))
}
