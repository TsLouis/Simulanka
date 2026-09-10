// Mirrors docs/design.md §12.2 / §12.4 — the payload shape the renderer consumes.

// Draw-time shape verdict for a user-drawn edge (§13.5.2). `match`/`mismatch`
// only when both endpoints are verified with shapes; `unknown` otherwise.
export type ShapeCheck = 'match' | 'mismatch' | 'unknown'

export type ExecutorFamily = 'GraphCommand' | 'SessionCommand' | 'ProjectionCommand'

export type ActionReasonCode =
  | 'available'
  | 'target_count_mismatch'
  | 'target_kind_mismatch'
  | 'unknown_profile'
  | 'missing_capability'
  | 'actor_forbidden'
  | 'source_read_only'
  | 'state_locked'
  | 'executor_unavailable'

export interface AffordanceDTO {
  id: string
  label: string
  enabled: boolean
  reason: string
  reason_code: ActionReasonCode
  input_schema: Record<string, unknown>
}

export interface EntitySemanticsDTO {
  capabilities: string[]
  unknown_profile: boolean
  affordances: AffordanceDTO[]
}

export interface PortDTO extends EntitySemanticsDTO {
  id: string
  node_id: string
  name: string
  side: 'in' | 'out'
  port_type: string
  attrs: Record<string, unknown>
}

// S6 可信级（服务端查询时算，不落盘）。null = 研究域之外，无徽记。
export type TrustLevel = 'human' | 'constructed' | 'reviewed' | 'checked' | 'unreviewed'

export interface NodeDTO extends EntitySemanticsDTO {
  id: string
  type: string
  name: string
  parent_id: string | null
  attrs: Record<string, unknown>
  ports: string[]
  child_count: number
  trust: TrustLevel | null
}

export interface EdgeDTO extends EntitySemanticsDTO {
  id: string
  type: string
  src: string
  dst: string
  src_port: string | null
  dst_port: string | null
  attrs: Record<string, unknown>
}

export interface ExternalNodeDTO extends EntitySemanticsDTO {
  id: string
  type: string
  name: string
}

export interface AncestorDTO extends EntitySemanticsDTO {
  id: string
  type: string
  name: string
}

export interface GraphPayload {
  registry_digest: string
  root: string | null
  // The container whose inside this view shows; null at top-level. The root
  // itself never appears in `nodes` — the crumb renders from here.
  root_info: AncestorDTO | null
  nodes: NodeDTO[]
  edges: EdgeDTO[]
  boundary_edges: EdgeDTO[]
  external_nodes: ExternalNodeDTO[]
  ports: PortDTO[]
  ancestors: AncestorDTO[]
}

export interface CapabilitySpecDTO {
  key: string
  consumers: ('validation' | 'action' | 'context' | 'presentation')[]
  description: string
}

export interface NodeProfileDescriptorDTO {
  key: string
  lineage: string[]
  capabilities: string[]
  allow_parents: (string | null)[]
  attrs_fields: Record<string, string>
  closed_attrs: boolean
  validators: string[]
  presentation: string | null
  tags: string[]
}

export interface EdgeProfileDescriptorDTO {
  key: string
  lineage: string[]
  capabilities: string[]
  needs_ports: boolean
  source_profiles: string[]
  target_profiles: string[]
  source_capabilities: string[]
  target_capabilities: string[]
  source_port_direction: 'in' | 'out' | null
  target_port_direction: 'in' | 'out' | null
  validators: string[]
  presentation: string | null
  tags: string[]
}

export interface PresentationSpecDTO {
  key: string
  category: string
  palette_token: string
  icon: string
  card_fields: string[]
  inspector_fields: string[]
  badges: string[]
}

export interface TemplateSpecDTO {
  key: string
  profile: string
  name: string
  category: string
  default_attrs: Record<string, unknown>
  default_ports: {
    name: string
    direction: 'in' | 'out'
    port_type: string
  }[]
}

export interface ActionSpecDTO {
  id: string
  label: string
  target: {
    min_count: number
    max_count: number | null
    entity_kinds: ('node' | 'edge' | 'port')[]
    capabilities: string[]
    target_match: 'all' | 'any'
  }
  executor: string
  executor_family: ExecutorFamily
  input_schema: Record<string, unknown>
}

export interface RegistryDescriptorDTO {
  version: number
  digest: string
  packages: string[]
  capabilities: CapabilitySpecDTO[]
  node_profiles: NodeProfileDescriptorDTO[]
  edge_profiles: EdgeProfileDescriptorDTO[]
  port_types: string[]
  presentations: PresentationSpecDTO[]
  templates: TemplateSpecDTO[]
  actions: ActionSpecDTO[]
  aliases: {
    node: Record<string, string>
    edge: Record<string, string>
    port: Record<string, string>
  }
}
