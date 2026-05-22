// Mirrors docs/design.md §12.2 / §12.4 — the payload shape the renderer consumes.

// Draw-time shape verdict for a user-drawn edge (§13.5.2). `match`/`mismatch`
// only when both endpoints are verified with shapes; `unknown` otherwise.
export type ShapeCheck = 'match' | 'mismatch' | 'unknown'

export interface PortDTO {
  id: string
  node_id: string
  name: string
  side: 'in' | 'out'
  port_type: string
  attrs: Record<string, unknown>
}

export interface NodeDTO {
  id: string
  type: string
  name: string
  parent_id: string | null
  attrs: Record<string, unknown>
  ports: string[]
  child_count: number
}

export interface EdgeDTO {
  id: string
  type: string
  src: string
  dst: string
  src_port: string | null
  dst_port: string | null
  attrs: Record<string, unknown>
}

export interface ExternalNodeDTO {
  id: string
  type: string
  name: string
}

export interface AncestorDTO {
  id: string
  type: string
  name: string
}

export interface GraphPayload {
  root: string | null
  nodes: NodeDTO[]
  edges: EdgeDTO[]
  boundary_edges: EdgeDTO[]
  external_nodes: ExternalNodeDTO[]
  ports: PortDTO[]
  ancestors: AncestorDTO[]
}
