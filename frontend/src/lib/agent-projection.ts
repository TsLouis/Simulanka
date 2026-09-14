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
const MAX_VISUALS = 4
const MAX_REFS = 24
const MAX_ATTENTION_REFS = 12
const MAX_DRAFT_NODES = 6
const MAX_DRAFT_EDGES = 8

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
    if (end < 0) {
      // During streaming, hide an unfinished projection block as soon as its
      // labelled opening fence arrives. It becomes parseable once later chunks
      // complete the closing fence.
      if (info === PROJECTION_LABEL) result = result.slice(0, start)
      break
    }
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

function uniqueAllowedRefs(
  values: unknown[],
  allowed: Map<string, ContextRefDTO>,
  max: number,
): ContextRefDTO[] {
  const refs: ContextRefDTO[] = []
  const seen = new Set<string>()
  for (const candidate of values) {
    const ref = allowedRef(candidate, allowed)
    if (!ref) continue
    const key = refKey(ref)
    if (seen.has(key)) continue
    seen.add(key)
    refs.push(ref)
    if (refs.length >= max) break
  }
  return refs
}

function parseVisual(
  value: unknown,
  allowed: Map<string, ContextRefDTO>,
): AgentVisualProjection | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const item = value as Record<string, unknown>

  if (item.kind === 'attention') {
    const refs = uniqueAllowedRefs(
      Array.isArray(item.refs) ? item.refs : [],
      allowed,
      MAX_ATTENTION_REFS,
    )
    if (refs.length === 0) return null
    return { kind: 'attention', refs, label: smallString(item.label, 72) }
  }

  if (item.kind === 'annotation') {
    const target = allowedRef(item.target, allowed)
    const text = smallString(item.text, 160)
    if (!target || !text) return null
    return { kind: 'annotation', target, text }
  }

  if (item.kind === 'draft_graph') {
    const anchor = allowedRef(item.anchor, allowed)
    if (!anchor) return null

    const nodes: AgentDraftGraphNode[] = []
    const nodeIds = new Set<string>()
    const rawNodes = Array.isArray(item.nodes) ? item.nodes : []
    for (const candidate of rawNodes) {
      if (nodes.length >= MAX_DRAFT_NODES) break
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue
      const node = candidate as Record<string, unknown>
      const id = smallString(node.id, 48)
      const label = smallString(node.label, 64)
      if (!id || !label || nodeIds.has(id)) continue
      nodeIds.add(id)
      nodes.push({ id, label, type: smallString(node.type, 40) })
    }
    if (nodes.length === 0) return null

    const edges: AgentDraftGraphEdge[] = []
    const seenEdges = new Set<string>()
    const rawEdges = Array.isArray(item.edges) ? item.edges : []
    for (const candidate of rawEdges) {
      if (edges.length >= MAX_DRAFT_EDGES) break
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue
      const edge = candidate as Record<string, unknown>
      const src = smallString(edge.src, 48)
      const dst = smallString(edge.dst, 48)
      if (!src || !dst || !nodeIds.has(src) || !nodeIds.has(dst)) continue
      const label = smallString(edge.label, 48)
      const key = `${src}\u0000${dst}\u0000${label ?? ''}`
      if (seenEdges.has(key)) continue
      seenEdges.add(key)
      edges.push({ src, dst, label })
    }
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
  // Provider adapters may split one textual answer into multiple completed
  // parts. Preserve the raw order exactly so a structured fence can span chunks.
  const rawText = agentChunks.join('').trim()
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
