import type { ContextRefDTO, SessionEventDTO } from './api'

export interface ConversationProjection {
  refs: ContextRefDTO[]
  text: string | null
}

function isContextRef(value: unknown): value is ContextRefDTO {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const candidate = value as Record<string, unknown>
  return (
    (candidate.kind === 'node' || candidate.kind === 'edge' || candidate.kind === 'port')
    && typeof candidate.ref_id === 'string'
    && candidate.ref_id.length > 0
  )
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
      const key = `${candidate.kind}:${candidate.ref_id}`
      if (seen.has(key)) continue
      seen.add(key)
      refs.push(candidate)
    }
  }
  return refs
}

/**
 * Derive the active conversation projection only from the latest explicit turn.
 *
 * The user_msg event is server-authored and records the actual ContextBundle
 * refs delivered for that turn. We intentionally do not infer targets from the
 * current selection, viewport, neighbouring graph objects, or agent prose.
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

  if (userIndex < 0 || refs.length === 0) return { refs: [], text: null }

  let text: string | null = null
  for (let index = events.length - 1; index > userIndex; index -= 1) {
    const event = events[index]
    if (event?.type === 'agent_text' && event.text) {
      text = event.text
      break
    }
  }
  return { refs, text }
}
