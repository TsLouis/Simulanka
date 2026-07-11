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

// --- §13.6 discussion session (agent ops ride the server write-matrix gate) -

export interface DiscussionOpResult {
  op: Record<string, unknown>
  reason?: string
  edge_id?: string
}

export interface DiscussionTurn {
  session_id: string
  reply: string
  applied: DiscussionOpResult[]
  rejected: DiscussionOpResult[]
  op_errors: string[]
}

export interface DiscussionState {
  active: boolean
  session_id?: string
  batch?: string[]
}

export async function startDiscussion(model?: string): Promise<DiscussionTurn> {
  const resp = await fetch('/discussion/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(model ? { model } : {}),
  })
  if (!resp.ok) {
    throw new Error(`POST /discussion/start failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as DiscussionTurn
}

export async function sendDiscussionMessage(text: string): Promise<DiscussionTurn> {
  const resp = await fetch('/discussion/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!resp.ok) {
    throw new Error(`POST /discussion/message failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as DiscussionTurn
}

export async function fetchDiscussionState(): Promise<DiscussionState> {
  const resp = await fetch('/discussion')
  if (!resp.ok) throw new Error(`GET /discussion failed: ${resp.status}`)
  return (await resp.json()) as DiscussionState
}

// --- S4 universal file viewer ----------------------------------------------

// A request to open the viewer: exactly one of node (file node id) / path
// (project-relative fs_path, e.g. an atom's plan_file attr). `highlight` is
// the generic open-and-highlight-a-term parameter (deep-link passes plan_lid).
export interface FileOpenRequest {
  node?: string
  path?: string
  highlight?: string
}

export interface FileContentDTO {
  id: string
  name: string
  kind: string | null
  fs_path: string
  size_bytes: number
  binary: boolean
  truncated: boolean
  content: string | null
}

export async function fetchFileContent(req: FileOpenRequest): Promise<FileContentDTO> {
  const params = new URLSearchParams()
  if (req.node) params.set('node', req.node)
  else if (req.path) params.set('path', req.path)
  const resp = await fetch(`/file/content?${params}`)
  if (!resp.ok) {
    throw new Error(`GET /file/content failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as FileContentDTO
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
