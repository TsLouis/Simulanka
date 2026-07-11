// S5 研究原子卡片：统一渲染器里 attr 驱动的展示模板。
//
// 呈现要求（2026-07-09 用户定为硬需求）：日常所需信息大多数不点开侧栏就能
// 从画布读到。实现边界（2026-07-10 定）：同一套节点画法与卡片骨架，每类
// 原子只是字段清单不同 —— 不做 per-type 分叉渲染。
//
// 字段清单（首版 Claude 定，彩排中按用户反馈迭代）：
//   question   = 正文摘要
//   hypothesis = verdict 徽记 + 正文摘要
//   claim      = status 徽记 + 正文摘要
//   experiment = status 徽记 + goal
//   task       = 预算徽记 + goal + 契约摘要（globs 数 · acceptance）
//   run        = status/contract_check 徽记 + 时长 · exit code
//   evidence   = 关键 metrics 数值（至多 3 行，多则 +N）
//   note       = ESCALATE/RESOLVED 徽记（kind=escalate）+ 正文摘要

import type { NodeDTO } from './types'

export type CardLine =
  | { kind: 'badges'; badges: Badge[] }
  | { kind: 'text'; text: string; mono?: boolean; dim?: boolean }

export interface Badge {
  text: string
  color: string
}

// 徽记语义色（app.css 调色板的 canvas 镜像，同 theme.ts 约定）
const JADE = '#7ecfa5' // 好结果：done / passed / supported / resolved
const AMBER = '#d9ba7d' // 待定：open / planned / pending
const CRIMSON = '#e07a68' // 坏结果：failed / refuted / out_of_scope / ESCALATE
const VIOLET = '#b28ce0' // 进行中：running
const MUTED = '#77839c' // 未判 / 未知

export const CARD_LINE_H = 15
export const CARD_WIDTH = 230

const str = (n: NodeDTO, key: string): string | null =>
  typeof n.attrs[key] === 'string' ? (n.attrs[key] as string) : null

const num = (n: NodeDTO, key: string): number | null =>
  typeof n.attrs[key] === 'number' ? (n.attrs[key] as number) : null

// 状态词 → 徽记色。未知词落灰 —— 不猜语义。
const STATUS_COLORS: Record<string, string> = {
  done: JADE,
  passed: JADE,
  supported: JADE,
  resolved: JADE,
  correct: JADE,
  open: AMBER,
  planned: AMBER,
  running: VIOLET,
  failed: CRIMSON,
  timed_out: CRIMSON,
  refuted: CRIMSON,
  wrong: CRIMSON,
  out_of_scope: CRIMSON,
  acceptance_failed: CRIMSON,
  uncertain: AMBER,
  disputed: CRIMSON,
  unconfirmed: MUTED,
}

const statusBadge = (word: string): Badge => ({
  text: word,
  color: STATUS_COLORS[word] ?? MUTED,
})

// CJK 感知的字符宽折行：全角算 2，半角算 1。canvas 逐节点 measureText 太贵，
// 字段清单本来就是可调项，字符预算截断对首版足够。
function clampLines(text: string, maxUnits = 30, maxLines = 2): CardLine[] {
  const out: string[] = []
  let line = ''
  let units = 0
  for (const ch of text.replace(/\s+/g, ' ').trim()) {
    const w = ch.charCodeAt(0) > 0xff ? 2 : 1
    if (units + w > maxUnits) {
      out.push(line)
      if (out.length === maxLines) {
        out[maxLines - 1] = out[maxLines - 1].slice(0, -1) + '…'
        return out.map(t => ({ kind: 'text', text: t }))
      }
      line = ''
      units = 0
    }
    line += ch
    units += w
  }
  if (line) out.push(line)
  return out.map(t => ({ kind: 'text', text: t }))
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m${Math.round(seconds % 60)}s`
  return `${(seconds / 3600).toFixed(1)}h`
}

// —— 每类原子的字段清单（表驱动；渲染骨架只有一个） ——————————————

type FieldList = (n: NodeDTO) => CardLine[]

const CARD_FIELDS: Record<string, FieldList> = {
  question: n => {
    const body = str(n, 'body')
    return body ? clampLines(body) : []
  },

  hypothesis: n => {
    const lines: CardLine[] = []
    const verdict = str(n, 'verdict')
    lines.push({
      kind: 'badges',
      badges: [verdict ? statusBadge(verdict) : { text: '未判', color: MUTED }],
    })
    const body = str(n, 'body')
    if (body) lines.push(...clampLines(body))
    return lines
  },

  claim: n => {
    const lines: CardLine[] = []
    const status = str(n, 'status')
    if (status) lines.push({ kind: 'badges', badges: [statusBadge(status)] })
    const body = str(n, 'body')
    if (body) lines.push(...clampLines(body))
    return lines
  },

  experiment: n => {
    const lines: CardLine[] = []
    lines.push({
      kind: 'badges',
      badges: [statusBadge(str(n, 'status') ?? 'planned')],
    })
    const goal = str(n, 'goal')
    if (goal) lines.push(...clampLines(goal))
    return lines
  },

  task: n => {
    const lines: CardLine[] = []
    const badges: Badge[] = []
    const budget = num(n, 'budget_time_seconds')
    if (budget !== null) badges.push({ text: `⏱ ${fmtDuration(budget)}`, color: AMBER })
    if (badges.length) lines.push({ kind: 'badges', badges })
    const goal = str(n, 'goal')
    if (goal) lines.push(...clampLines(goal))
    const globs = Array.isArray(n.attrs.allowed_outputs)
      ? (n.attrs.allowed_outputs as unknown[]).length
      : 0
    const acceptance = str(n, 'acceptance_command')
    const contract = [
      globs > 0 ? `⛓ ${globs} glob${globs > 1 ? 's' : ''}` : null,
      acceptance ? `✓ ${acceptance}` : null,
    ].filter(Boolean).join(' · ')
    if (contract) {
      const clamped = clampLines(contract, 34, 1)[0]
      if (clamped.kind === 'text') lines.push({ ...clamped, mono: true, dim: true })
    }
    return lines
  },

  run: n => {
    const lines: CardLine[] = []
    const badges: Badge[] = []
    const status = str(n, 'status')
    if (status) badges.push(statusBadge(status))
    const check = n.attrs.contract_check
    if (check && typeof check === 'object') {
      const cs = (check as Record<string, unknown>).status
      if (typeof cs === 'string') badges.push(statusBadge(cs))
    }
    if (badges.length) lines.push({ kind: 'badges', badges })
    const duration = num(n, 'duration_seconds')
    const exit = num(n, 'exit_code')
    const meta = [
      duration !== null ? `⏱ ${fmtDuration(duration)}` : status === 'running' ? '⏱ …' : null,
      exit !== null ? `exit ${exit}` : null,
    ].filter(Boolean).join(' · ')
    if (meta) lines.push({ kind: 'text', text: meta, mono: true, dim: true })
    return lines
  },

  evidence: n => {
    const metrics = n.attrs.metrics
    if (!metrics || typeof metrics !== 'object') {
      const body = str(n, 'body')
      return body ? clampLines(body) : []
    }
    const entries = Object.entries(metrics as Record<string, unknown>).sort(
      ([a], [b]) => a.localeCompare(b),
    )
    const lines: CardLine[] = entries.slice(0, 3).map(([k, v]) => {
      const clamped = clampLines(`${k} = ${String(v)}`, 32, 1)[0]
      return clamped.kind === 'text' ? { ...clamped, mono: true } : clamped
    })
    if (entries.length > 3) {
      lines.push({ kind: 'text', text: `+${entries.length - 3} more`, dim: true })
    }
    return lines
  },

  note: n => {
    const lines: CardLine[] = []
    if (str(n, 'kind') === 'escalate') {
      const resolved = str(n, 'status') === 'resolved'
      lines.push({
        kind: 'badges',
        badges: [
          resolved
            ? { text: 'RESOLVED', color: JADE }
            : { text: 'ESCALATE', color: CRIMSON },
        ],
      })
    }
    const body = str(n, 'body')
    if (body) lines.push(...clampLines(body))
    return lines
  },
}

/** 该节点的卡片行；结构类型（model/module/directory/file…）返回空 = 无卡片。 */
export function cardLines(n: NodeDTO): CardLine[] {
  const fields = CARD_FIELDS[n.type]
  return fields ? fields(n) : []
}
