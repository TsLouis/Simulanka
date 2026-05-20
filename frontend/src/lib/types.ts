// Mirrors docs/design.md §12.2 — the single payload shape the renderer consumes.

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

export interface GraphPayload {
  root: string | null
  nodes: NodeDTO[]
  edges: EdgeDTO[]
  ports: PortDTO[]
}
