export const AGENT_REF_MIME = 'application/x-simulanka-ref'

export type AgentDragKind = 'node' | 'edge' | 'port'

export interface AgentDragRef {
  kind: AgentDragKind
  ref_id: string
  label: string
}

const isKind = (value: unknown): value is AgentDragKind =>
  value === 'node' || value === 'edge' || value === 'port'

export function writeAgentDragRef(event: DragEvent, ref: AgentDragRef): void {
  const transfer = event.dataTransfer
  if (!transfer) return
  transfer.effectAllowed = 'copy'
  transfer.setData(AGENT_REF_MIME, JSON.stringify(ref))
  // Plain text is only a harmless accessibility/fallback label; Agent context
  // is created exclusively from the typed custom payload above.
  transfer.setData('text/plain', ref.label)
}

export function hasAgentDragRef(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes(AGENT_REF_MIME)
}

export function readAgentDragRef(event: DragEvent): AgentDragRef | null {
  const transfer = event.dataTransfer
  if (!transfer) return null
  try {
    const raw = transfer.getData(AGENT_REF_MIME)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<AgentDragRef>
    if (!isKind(value.kind)) return null
    if (typeof value.ref_id !== 'string' || value.ref_id.length === 0) return null
    if (typeof value.label !== 'string' || value.label.length === 0) return null
    return { kind: value.kind, ref_id: value.ref_id, label: value.label }
  } catch {
    return null
  }
}
