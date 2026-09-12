export const AGENT_REF_MIME = 'application/x-simulanka-ref'

export type AgentDragKind = 'node' | 'edge' | 'port'

export interface AgentDragRef {
  kind: AgentDragKind
  ref_id: string
  label: string
}

const isKind = (value: unknown): value is AgentDragKind =>
  value === 'node' || value === 'edge' || value === 'port'

function parseRef(value: unknown): AgentDragRef | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const candidate = value as Partial<AgentDragRef>
  if (!isKind(candidate.kind)) return null
  if (typeof candidate.ref_id !== 'string' || candidate.ref_id.length === 0) return null
  if (typeof candidate.label !== 'string' || candidate.label.length === 0) return null
  return {
    kind: candidate.kind,
    ref_id: candidate.ref_id,
    label: candidate.label,
  }
}

export function writeAgentDragRefs(event: DragEvent, refs: AgentDragRef[]): void {
  const transfer = event.dataTransfer
  if (!transfer || refs.length === 0) return
  transfer.effectAllowed = 'copy'
  transfer.setData(AGENT_REF_MIME, JSON.stringify(refs))
  // Plain text is only a harmless accessibility/fallback label; Agent context
  // is created exclusively from the typed custom payload above.
  transfer.setData(
    'text/plain',
    refs.length === 1 ? refs[0].label : `${refs.length} Simulanka objects`,
  )
}

export function writeAgentDragRef(event: DragEvent, ref: AgentDragRef): void {
  writeAgentDragRefs(event, [ref])
}

export function hasAgentDragRef(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes(AGENT_REF_MIME)
}

export function readAgentDragRefs(event: DragEvent): AgentDragRef[] {
  const transfer = event.dataTransfer
  if (!transfer) return []
  try {
    const raw = transfer.getData(AGENT_REF_MIME)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    // Accept the original single-ref shape as a compatibility path for any
    // in-flight drag created before this module hot-reloads.
    const values = Array.isArray(parsed) ? parsed : [parsed]
    const refs: AgentDragRef[] = []
    const seen = new Set<string>()
    for (const value of values) {
      const ref = parseRef(value)
      if (!ref) continue
      const key = `${ref.kind}:${ref.ref_id}`
      if (seen.has(key)) continue
      seen.add(key)
      refs.push(ref)
    }
    return refs
  } catch {
    return []
  }
}

export function readAgentDragRef(event: DragEvent): AgentDragRef | null {
  return readAgentDragRefs(event)[0] ?? null
}
