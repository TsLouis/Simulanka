import type { ContextRefDTO, SessionEventDTO } from './api'

export interface AgentAttentionProjection {
  kind: 'attention'
  refs: ContextRefDTO[]
  label: string | null
}

export interface AgentAnnotationProjection {
  kind: 'annotation'
  target: ContextRefDTO
  text: string
}

export interface AgentDraftGraphNode {
  id: string
  label: string
  type: string | null
}

export interface AgentDraftGraphEdge {
  src: string
  dst: string
  label: string | null
}

export interface AgentDraftGraphProjection {
  kind: 'draft_graph'
  anchor: ContextRefDTO
  nodes: AgentDraftGraphNode[]
  edges: AgentDraftGraphEdge[]
}

export type AgentVisualProjection =
  | AgentAttentionProjection
  | AgentAnnotationProjection
  | AgentDraftGraphProjection

export interface ConversationProjection {
  refs: ContextRefDTO[]
  text: string | null
  visuals: AgentVisualProjection[]
}

const EMPTY_PROJECTION: ConversationProjection = { refs: [], text: null, visuals: [] }
let activeProjection: ConversationProjection = EMPTY_PROJECTION
const listeners = new Set<(projection: ConversationProjection) => void>()
const FENCE = '```'
const PROJECTION_LABEL = 'simulanka-projection'
const MAX_VISUALS = 8
const MAX_REFS = 24
const MAX_DRAFT_NODES = 10
const MAX_DRAFT_EDGES = 18

function isContextRef(value: unknown): value is ContextRefDTO {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const candidate = value as Record<string, unknown>
  return (
    (candidate.kind === 'node' || candidate.kind === 'edge' || candidate.kind === 'port')
    && typeof candidate.ref_id === 'string'
    && candidate.ref_id.length > 0
  )
}

function refKey(ref: ContextRefDTO): string {
  return `${ref.kind}:${ref.ref_id}`
}

function refsFromUserEvent(event: SessionEventDTO): ContextRefDTO[] {
  if (event.type !== 'user_msg') return []
  const bundles = event.details?.context_bundles
  if (!Array.isArray(bundles)) return []

  const refs: ContextRefDTO[] = []
  const seen = new Set<string>()
  for (const bundle of bundles) {
    if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) continue
    const bundleRefs = (bundle as Record<string, unknown>).refs
    if (!Array.isArray(bundleRefs)) continue
    for (const candidate of bundleRefs) {
      if (!isContextRef(candidate)) continue
      const key = refKey(candidate)
      if (seen.has(key)) continue
      seen.add(key)
      refs.push(candidate)
    }
  }
  return refs.slice(0, MAX_REFS)
}

function fencedBlocks(text: string, label: string): string[] {
  const blocks: string[] = []
  let pos = 0
  while (true) {
    const start = text.indexOf(FENCE, pos)
    if (start < 0) return blocks
    const lineEnd = text.indexOf('\n', start + FENCE.length)
    if (lineEnd < 0) return blocks
    const info = text.slice(start + FENCE.length, lineEnd).trim().toLowerCase()
    const end = text.indexOf(FENCE, lineEnd + 1)
    if (end < 0) return blocks
    if (info === label) blocks.push(text.slice(lineEnd + 1, end).trim())
    pos = end + FENCE.length
  }
}

export function stripProjectionBlocks(text: string): string {
  let result = text
  let pos = 0
  while (true) {
    const start = result.indexOf(FENCE, pos)
    if (start < 0) break
    const lineEnd = result.indexOf('\n', start + FENCE.length)
    if (lineEnd < 0) break
    const info = result.slice(start + FENCE.length, lineEnd).trim().toLowerCase()
    const end = result.indexOf(FENCE, lineEnd + 1)
    if (end < 0) break
    if (info !== PROJECTION_LABEL) {
      pos = end + FENCE.length
      continue
    }
    result = `${result.slice(0, start)}${result.slice(end + FENCE.length)}`
    pos = Math.max(0, start - 1)
  }
  return result.replace(/\n{3,}/g, '\n\n').trim()
}

function smallString(value: unknown, max = 240): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim()
  return text ? text.slice(0, max) : null
}

function allowedRef(value: unknown, allowed: Map<string, ContextRefDTO>): ContextRefDTO | null {
  if (!isContextRef(value)) return null
  return allowed.get(refKey(value)) ?? null
}

function parseVisual(
  value: unknown,
  allowed: Map<string, ContextRefDTO>,
): AgentVisualProjection | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const item = value as Record<string, unknown>

  if (item.kind === 'attention') {
    const refs = (Array.isArray(item.refs) ? item.refs : [])
      .map(candidate => allowedRef(candidate, allowed))
      .filter((ref): ref is ContextRefDTO => ref !== null)
      .slice(0, MAX_REFS)
    if (refs.length === 0) return null
    return { kind: 'attention', refs, label: smallString(item.label, 100) }
  }

  if (item.kind === 'annotation') {
    const target = allowedRef(item.target, allowed)
    const text = smallString(item.text)
    if (!target || !text) return null
    return { kind: 'annotation', target, text }
  }

  if (item.kind === 'draft_graph') {
    const anchor = allowedRef(item.anchor, allowed)
    if (!anchor) return null
    const nodes = (Array.isArray(item.nodes) ? item.nodes : [])
      .slice(0, MAX_DRAFT_NODES)
      .map((candidate): AgentDraftGraphNode | null => {
        if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return null
        const node = candidate as Record<string, unknown>
        const id = smallString(node.id, 60)
        const label = smallString(node.label, 90)
        if (!id || !label) return null
        return { id, label, type: smallString(node.type, 50) }
      })
      .filter((node): node is AgentDraftGraphNode => node !== null)
    if (nodes.length === 0) return null
    const nodeIds = new Set(nodes.map(node => node.id))
    const edges = (Array.isArray(item.edges) ? item.edges : [])
      .slice(0, MAX_DRAFT_EDGES)
      .map((candidate): AgentDraftGraphEdge | null => {
        if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return null
        const edge = candidate as Record<string, unknown>
        const src = smallString(edge.src, 60)
        const dst = smallString(edge.dst, 60)
        if (!src || !dst || !nodeIds.has(src) || !nodeIds.has(dst)) return null
        return { src, dst, label: smallString(edge.label, 70) }
      })
      .filter((edge): edge is AgentDraftGraphEdge => edge !== null)
    return { kind: 'draft_graph', anchor, nodes, edges }
  }

  return null
}

function structuredVisuals(text: string, allowedRefs: ContextRefDTO[]): AgentVisualProjection[] {
  if (allowedRefs.length === 0) return []
  const allowed = new Map(allowedRefs.map(ref => [refKey(ref), ref]))
  const visuals: AgentVisualProjection[] = []
  for (const body of fencedBlocks(text, PROJECTION_LABEL)) {
    let payload: unknown
    try {
      payload = JSON.parse(body)
    } catch {
      continue
    }
    const raw = Array.isArray(payload)
      ? payload
      : payload && typeof payload === 'object' && Array.isArray((payload as Record<string, unknown>).projections)
        ? (payload as Record<string, unknown>).projections as unknown[]
        : [payload]
    for (const candidate of raw) {
      const projection = parseVisual(candidate, allowed)
      if (projection) visuals.push(projection)
      if (visuals.length >= MAX_VISUALS) return visuals
    }
  }
  return visuals
}

/**
 * Derive the active conversation layer from the latest explicit turn.
 *
 * The user_msg event is server-authored and records the actual ContextBundle
 * refs delivered for that turn. Structured projection blocks may only target
 * those refs. We never infer targets from the current selection, viewport,
 * neighbouring graph objects, or free-form prose.
 */
export function conversationProjectionFromEvents(
  events: SessionEventDTO[],
): ConversationProjection {
  let userIndex = -1
  let refs: ContextRefDTO[] = []
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.type !== 'user_msg') continue
    userIndex = index
    refs = refsFromUserEvent(events[index])
    break
  }

  if (userIndex < 0 || refs.length === 0) return EMPTY_PROJECTION

  const agentChunks: string[] = []
  for (let index = userIndex + 1; index < events.length; index += 1) {
    const event = events[index]
    if (event?.type === 'agent_text' && event.text) agentChunks.push(event.text)
  }
  const rawText = agentChunks.join('\n').trim()
  const visuals = structuredVisuals(rawText, refs)
  const visibleText = stripProjectionBlocks(rawText)
  return {
    refs,
    text: visibleText || null,
    visuals,
  }
}

function projectionKey(projection: ConversationProjection): string {
  return JSON.stringify([
    projection.refs.map(ref => [ref.kind, ref.ref_id]),
    projection.text,
    projection.visuals,
  ])
}

/**
 * Publish a UI/session sidecar projection. This never mutates the semantic graph.
 * Consumers such as the canvas projection layer redraw attention/annotation/draft
 * overlays only; accepting anything into the graph remains a separate action.
 */
export function setConversationProjection(projection: ConversationProjection): void {
  const normalized: ConversationProjection = {
    refs: projection.refs.map(ref => ({ kind: ref.kind, ref_id: ref.ref_id })),
    text: projection.text,
    visuals: projection.visuals,
  }
  if (projectionKey(normalized) === projectionKey(activeProjection)) return
  activeProjection = normalized
  for (const listener of listeners) listener(activeProjection)
}

export function getConversationProjection(): ConversationProjection {
  return activeProjection
}

export function subscribeConversationProjection(
  listener: (projection: ConversationProjection) => void,
): () => void {
  listeners.add(listener)
  listener(activeProjection)
  return () => listeners.delete(listener)
}
