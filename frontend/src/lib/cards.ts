import type { NodeDTO, PresentationSpecDTO } from './types'

export type CardLine =
  | { kind: 'badges'; badges: Badge[] }
  | { kind: 'text'; text: string; mono?: boolean; dim?: boolean }

export interface Badge {
  text: string
  color: string
}

const JADE = '#7ecfa5'
const AMBER = '#d9ba7d'
const CRIMSON = '#e07a68'
const VIOLET = '#b28ce0'
const MUTED = '#77839c'

export const CARD_LINE_H = 15
export const CARD_WIDTH = 230
const MAX_CARD_LINES = 5

const STATUS_COLORS: Record<string, string> = {
  done: JADE,
  passed: JADE,
  supported: JADE,
  resolved: JADE,
  correct: JADE,
  open: AMBER,
  planned: AMBER,
  pending: AMBER,
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
  escalate: CRIMSON,
}

function statusBadge(value: string): Badge {
  return {
    text: value,
    color: STATUS_COLORS[value.toLowerCase()] ?? MUTED,
  }
}

function clampLines(text: string, maxUnits = 32, maxLines = 2): CardLine[] {
  const out: string[] = []
  let line = ''
  let units = 0
  for (const char of text.replace(/\s+/g, ' ').trim()) {
    const width = char.charCodeAt(0) > 0xff ? 2 : 1
    if (units + width > maxUnits) {
      out.push(line)
      if (out.length === maxLines) {
        out[maxLines - 1] = `${out[maxLines - 1].slice(0, -1)}…`
        return out.map(value => ({ kind: 'text', text: value }))
      }
      line = ''
      units = 0
    }
    line += char
    units += width
  }
  if (line) out.push(line)
  return out.map(value => ({ kind: 'text', text: value }))
}

function readField(attrs: Record<string, unknown>, path: string): unknown {
  let value: unknown = attrs
  for (const part of path.split('.')) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
    value = (value as Record<string, unknown>)[part]
  }
  return value
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m${Math.round(seconds % 60)}s`
  return `${(seconds / 3600).toFixed(1)}h`
}

function displayValue(key: string, value: unknown, formatter = 'raw'): CardLine[] {
  if (value === null || value === undefined || value === '') return []
  if (formatter === 'metrics' && typeof value === 'object' && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .slice(0, 3)
    const lines: CardLine[] = entries.flatMap(([metric, metricValue]) =>
      clampLines(`${metric} = ${String(metricValue)}`, 32, 1)
        .map(line => ({ ...line, mono: true })),
    )
    const total = Object.keys(value).length
    if (total > entries.length) {
      lines.push({ kind: 'text', text: `+${total - entries.length} more`, dim: true })
    }
    return lines
  }

  if (formatter === 'duration' && typeof value === 'number') {
    return [{ kind: 'text', text: `⏱ ${formatDuration(value)}`, mono: true, dim: true }]
  }
  if (formatter === 'count' && Array.isArray(value)) {
    return [{ kind: 'text', text: `⛓ ${value.length} item${value.length === 1 ? '' : 's'}`, mono: true, dim: true }]
  }
  if (formatter === 'exit-code' && typeof value === 'number') {
    return [{ kind: 'text', text: `exit ${value}`, mono: true, dim: true }]
  }

  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (!text) return []
  const labelled = formatter === 'text'
    ? text
    : formatter === 'command'
      ? `✓ ${text}`
      : `${key} = ${text}`
  return clampLines(labelled, 32, 2).map(line => ({
    ...line,
    mono: formatter !== 'text',
    dim: formatter === 'command',
  }))
}

function genericFields(node: NodeDTO): string[] {
  return Object.keys(node.attrs)
    .sort()
    .slice(0, 2)
}

/** Render only declarative PresentationSpec fields; unknown Profiles get a stable fallback. */
export function cardLines(
  node: NodeDTO,
  presentation: PresentationSpecDTO | null,
): CardLine[] {
  const lines: CardLine[] = []
  if (!presentation) {
    // The LiteGraph title already carries name; this line keeps type visible
    // for an uninstalled/unknown Profile while the following lines expose attrs.
    lines.push({ kind: 'text', text: node.type, mono: true, dim: true })
  } else {
    const badges = presentation.badges
      .flatMap(key => {
        const value = readField(node.attrs, key)
        if (!['string', 'number', 'boolean'].includes(typeof value)) return []
        if (presentation.formatters[key] === 'duration' && typeof value === 'number') {
          return [{ text: `⏱ ${formatDuration(value)}`, color: AMBER }]
        }
        return [statusBadge(String(value))]
      })
    if (badges.length > 0) lines.push({ kind: 'badges', badges })
  }

  const fields = presentation?.card_fields ?? genericFields(node)
  for (const key of fields) {
    lines.push(...displayValue(
      key,
      readField(node.attrs, key),
      presentation?.formatters[key],
    ))
    if (lines.length >= MAX_CARD_LINES) break
  }
  return lines.slice(0, MAX_CARD_LINES)
}
