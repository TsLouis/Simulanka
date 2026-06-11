import type { DisagreementDTO, GraphPayload, ShapeCheck } from './types'

export async function fetchGraph(
  root: string | null,
  depth: number,
): Promise<GraphPayload> {
  const params = new URLSearchParams()
  if (root !== null) params.set('root', root)
  params.set('depth', String(depth))
  const resp = await fetch(`/graph?${params}`)
  if (!resp.ok) {
    throw new Error(`GET /graph failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as GraphPayload
}

// Persist a user-drawn data_flow edge (§13.5.2). Returns the new edge id.
export async function createEdge(
  srcPort: string,
  dstPort: string,
  shapeCheck: ShapeCheck,
): Promise<string> {
  const resp = await fetch('/edge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src_port: srcPort, dst_port: dstPort, shape_check: shapeCheck }),
  })
  if (!resp.ok) {
    throw new Error(`POST /edge failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()).edge_id as string
}

export async function deleteEdge(edgeId: string): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}`, { method: 'DELETE' })
  if (!resp.ok) {
    throw new Error(`DELETE /edge failed: ${resp.status} ${await resp.text()}`)
  }
}

// --- §13.6 verify-discuss -------------------------------------------------

// Accept a proposed ghost edge (同意即连). Only valid on a ghost; the server
// 422s anything else.
export async function acceptGhost(edgeId: string): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}/accept`, { method: 'POST' })
  if (!resp.ok) {
    throw new Error(`POST /edge/accept failed: ${resp.status} ${await resp.text()}`)
  }
}

// Human verdict write-back. `note` is server-enforced non-empty: defending the
// judgment is the §13.6 learning moment.
export async function postVerdict(
  edgeId: string,
  verdict: 'correct' | 'wrong' | 'disputed',
  note: string,
): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}/verdict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ verdict, note }),
  })
  if (!resp.ok) {
    throw new Error(`POST /edge/verdict failed: ${resp.status} ${await resp.text()}`)
  }
}

// Pull an edge into (true) or out of (false) the discussion set by hand.
export async function setDiscuss(edgeId: string, discuss: boolean): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}/discuss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discuss }),
  })
  if (!resp.ok) {
    throw new Error(`POST /edge/discuss failed: ${resp.status} ${await resp.text()}`)
  }
}

export async function fetchDisagreements(): Promise<DisagreementDTO[]> {
  const resp = await fetch('/disagreements')
  if (!resp.ok) {
    throw new Error(`GET /disagreements failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()).disagreements as DisagreementDTO[]
}

// Per-view-root maps of node id → [x, y]. "top" is the top-level view key.
export type Positions = Record<string, Record<string, [number, number]>>

export async function fetchPositions(): Promise<Positions> {
  const resp = await fetch('/ui/positions')
  if (!resp.ok) throw new Error(`GET /ui/positions failed: ${resp.status}`)
  return (await resp.json()) as Positions
}

export async function savePositions(
  rootKey: string,
  positions: Record<string, [number, number]>,
): Promise<void> {
  const resp = await fetch(`/ui/positions/${encodeURIComponent(rootKey)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(positions),
  })
  if (!resp.ok) {
    throw new Error(`POST /ui/positions failed: ${resp.status} ${await resp.text()}`)
  }
}
