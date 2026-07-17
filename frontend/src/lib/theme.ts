// 「星图册 · Starlit Atlas」canvas 侧主题 —— CSS 吃不到 canvas，这里是
// app.css 变量表的 canvas 镜像（两处改动须同步，hex 以 app.css 注释互指）。
// 研究图即星座图：夜空、星卡、星光丝线。
import { LGraphCanvas, LiteGraph, type LGraphNode } from 'litegraph.js'

/** 画布夜空底色（= app.css --sky）。 */
export const SKY = '#0b1322'

/** 边的出处三色（= app.css --star/--amber/--violet；§13.2 前端三色区分）。 */
export const EDGE_COLORS: Record<string, string> = {
  trace: '#8fb8e8', // 星蓝 —— 机器观测的星光
  user: '#e3b566', // 金线 —— 人的手笔
  agent: '#b28ce0', // 紫晶 —— agent 主张
}
/** 血缘丝线（fulfills/produces 等无端口语义边）：比星蓝暗一档的底层丝线，
 *  画在节点层之下——是系统的账，不与数据流的三色抢戏。 */
export const LINEAGE_COLOR = '#44557d'
/** 未核 ghost：低语一样的灰蓝虚线。 */
export const GHOST_COLOR = '#77839c'
/** 被人拒绝的 ghost：绯红，读作「有争议」（= app.css --crimson）。 */
export const REJECTED_GHOST_COLOR = '#e07a68'
/** 端口置信度（= app.css --jade / --muted 系）。 */
export const VERIFIED_COLOR = '#7ecfa5'
export const INFERRED_COLOR = '#77839c'

/** S6 可信级五色（frontend.md 映射表）：只染节点体，边色不叠加。 */
export const TRUST_COLORS: Record<string, string> = {
  human: '#e3b566', // 金 —— 人裁
  constructed: '#8fb8e8', // 星蓝 —— 机器观测（与 trace 边同色）
  reviewed: '#7ecfa5', // 玉 —— 分析者 distill 复核
  checked: '#d9ba7d', // 琥珀 —— 快检章（动态线词表先定）
  unreviewed: '#77839c', // 灰 —— 「未定」应显眼地不显眼
}

/** 星卡配色：LiteGraph node.color = 标题条，bgcolor = 卡身，boxcolor = 徽点。 */
interface NodeStyle {
  color: string
  bgcolor: string
  boxcolor: string
}
const CARD = '#151f38'
const NODE_STYLES: Record<string, NodeStyle> = {
  model: { color: '#3f3419', bgcolor: '#1b2138', boxcolor: '#e3b566' },
  module: { color: '#20304f', bgcolor: CARD, boxcolor: '#8fb8e8' },
  directory: { color: '#2a3550', bgcolor: CARD, boxcolor: '#93794a' },
  experiment: { color: '#1d3a30', bgcolor: '#152034', boxcolor: '#7ecfa5' },
  run: { color: '#2c2a4a', bgcolor: CARD, boxcolor: '#b28ce0' },
  task: { color: '#3a2c22', bgcolor: CARD, boxcolor: '#e3b566' },
  question: { color: '#243a52', bgcolor: CARD, boxcolor: '#8fb8e8' },
  hypothesis: { color: '#332c50', bgcolor: CARD, boxcolor: '#b28ce0' },
  claim: { color: '#3f3419', bgcolor: CARD, boxcolor: '#f2d9a4' },
  evidence: { color: '#1d3a30', bgcolor: CARD, boxcolor: '#7ecfa5' },
  note: { color: '#33301f', bgcolor: CARD, boxcolor: '#d9ba7d' },
  file: { color: '#232c42', bgcolor: CARD, boxcolor: '#8d99b5' },
}
const NODE_DEFAULT: NodeStyle = { color: '#24304e', bgcolor: CARD, boxcolor: '#93794a' }
/** 边界桩子：半透明幽影 —— 它是子图取景框的投影，不是真节点。 */
const NODE_BOUNDARY: NodeStyle = { color: '#1a2233', bgcolor: '#10182bcc', boxcolor: '#5a6a8f' }

/** 给一张星卡上色。`boundary` 走幽影样式。 */
export function styleNode(node: LGraphNode, type: string): void {
  const s = type === 'boundary' ? NODE_BOUNDARY : (NODE_STYLES[type] ?? NODE_DEFAULT)
  const n = node as unknown as Record<string, unknown>
  n.color = s.color
  n.bgcolor = s.bgcolor
  n.boxcolor = s.boxcolor
}

const CANVAS_FONT = "'Noto Sans SC', ui-sans-serif, sans-serif"

/** 夜空 + 星卡的全局装置：底色、星野、字体、LiteGraph 全局配色。
 * 只需在 LGraphCanvas 构造后调用一次。 */
export function applyNightSky(canvas: LGraphCanvas): void {
  const lg = LiteGraph as unknown as Record<string, unknown>
  lg.NODE_TITLE_COLOR = '#e9d9b0' // 象牙金标题字
  lg.NODE_SELECTED_TITLE_COLOR = '#f2d9a4'
  lg.NODE_TEXT_COLOR = '#c9d2e4'
  lg.NODE_DEFAULT_COLOR = '#24304e'
  lg.NODE_DEFAULT_BGCOLOR = CARD
  lg.NODE_DEFAULT_BOXCOLOR = '#93794a'
  lg.NODE_BOX_OUTLINE_COLOR = '#f2d9a4' // 选中描金
  lg.WIDGET_BGCOLOR = '#0f1830'
  lg.LINK_COLOR = '#44557d'
  lg.EVENT_LINK_COLOR = '#e3b566'
  lg.CONNECTING_LINK_COLOR = '#f2d9a4' // 拉线时的金丝

  const c = canvas as unknown as Record<string, unknown>
  c.background_image = null // 关掉默认网格，让星野接管
  c.show_info = false // 左下角 FPS 调试角标不属于星图
  c.clear_background_color = SKY
  c.render_canvas_border = false
  c.render_connections_border = false
  c.default_link_color = '#44557d'
  c.title_text_font = `500 13px ${CANVAS_FONT}`
  c.inner_text_font = `normal 11px ${CANVAS_FONT}`
  c.round_radius = 6

  c.onDrawBackground = (ctx: CanvasRenderingContext2D, area: [number, number, number, number]) => {
    drawStarfield(ctx, area)
  }

  // 双击容器节点是我们的下钻手势；LiteGraph 原生的 node Properties 面板
  // （带 Delete，且不走 kernel）在同一手势上弹出——压掉，NodeInspector
  // 是唯一的节点详情面。
  c.onShowNodePanel = () => {}

  // Web 字体就绪后重绘一次，否则首帧 canvas 文字落回退字体。
  const fonts = (document as Document & { fonts?: FontFaceSet }).fonts
  void fonts?.ready.then(() => canvas.setDirty(true, true))
}

// 星野：图空间坐标下按网格 cell 决定性撒星（同一 cell 永远同一颗星），
// 平移缩放时星随图动 —— 整张图就是一幅会动的星图。零状态、零动画开销。
const CELL = 150

function hash2(ix: number, iy: number, salt: number): number {
  let h = (ix * 374761393 + iy * 668265263 + salt * 2246822519) | 0
  h = ((h ^ (h >>> 13)) * 1274126177) | 0
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295
}

function drawStarfield(
  ctx: CanvasRenderingContext2D,
  [ax, ay, aw, ah]: [number, number, number, number],
): void {
  const x0 = Math.floor(ax / CELL) - 1
  const y0 = Math.floor(ay / CELL) - 1
  const x1 = Math.ceil((ax + aw) / CELL) + 1
  const y1 = Math.ceil((ay + ah) / CELL) + 1
  ctx.save()
  for (let iy = y0; iy <= y1; iy++) {
    for (let ix = x0; ix <= x1; ix++) {
      const presence = hash2(ix, iy, 1)
      if (presence > 0.85) continue // 留出呼吸的空区
      const sx = (ix + hash2(ix, iy, 2)) * CELL
      const sy = (iy + hash2(ix, iy, 3)) * CELL
      const size = 0.5 + hash2(ix, iy, 4) * 1.3
      const alpha = 0.08 + hash2(ix, iy, 5) * 0.35
      const golden = hash2(ix, iy, 6) > 0.92 // 少数星是金的
      ctx.fillStyle = golden
        ? `rgba(242, 217, 164, ${alpha + 0.15})`
        : `rgba(190, 210, 240, ${alpha})`
      ctx.beginPath()
      ctx.arc(sx, sy, size, 0, Math.PI * 2)
      ctx.fill()
      if (golden) {
        // 金星带一枚小小的四芒
        const r = size * 4
        ctx.strokeStyle = `rgba(242, 217, 164, ${alpha * 0.6})`
        ctx.lineWidth = 0.6
        ctx.beginPath()
        ctx.moveTo(sx - r, sy)
        ctx.lineTo(sx + r, sy)
        ctx.moveTo(sx, sy - r)
        ctx.lineTo(sx, sy + r)
        ctx.stroke()
      }
    }
  }
  ctx.restore()
}
