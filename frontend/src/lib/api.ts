import type { GraphPayload, ShapeCheck, TrustLevel } from './types'

// One view = the inside of one container (root's direct children); navigation
// is drill-down/breadcrumb only. There is no depth knob — the server contract
// never mixes levels.
export async function fetchGraph(root: string | null): Promise<GraphPayload> {
  const params = new URLSearchParams()
  if (root !== null) params.set('root', root)
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

// --- canvas authoring: add / rename nodes, custom templates -----------------

export interface CreateNodeRequest {
  type: string
  name: string
  parent: string | null
  attrs: Record<string, unknown>
  ports: { name: string; direction: 'in' | 'out'; port_type?: string }[]
}

export interface CreateNodeResult {
  node_id: string
  name: string
  port_ids: string[]
  graph_version: number
}

export async function createNode(req: CreateNodeRequest): Promise<CreateNodeResult> {
  const resp = await fetch('/node', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) {
    throw new Error(`POST /node failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as CreateNodeResult
}

// Delete an empty module/model node (kernel cascades ports + incident edges).
// Non-empty or out-of-domain nodes come back as a 422 with the reason.
export async function deleteNode(nodeId: string): Promise<void> {
  const resp = await fetch(`/node/${encodeURIComponent(nodeId)}`, { method: 'DELETE' })
  if (!resp.ok) {
    throw new Error(`delete failed: ${resp.status} ${await resp.text()}`)
  }
}

export async function renameNode(nodeId: string, newName: string): Promise<void> {
  const resp = await fetch(`/node/${encodeURIComponent(nodeId)}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_name: newName }),
  })
  if (!resp.ok) {
    throw new Error(`rename failed: ${resp.status} ${await resp.text()}`)
  }
}

// Custom templates live on the server (.simulanka/ui/templates.json), keyed
// by template name — UI state like positions, not graph entities.
export interface CustomTemplateDTO {
  category: string
  type: string
  attrs: Record<string, unknown>
  ports: { name: string; direction: 'in' | 'out'; port_type?: string }[]
}

export async function fetchTemplates(): Promise<Record<string, CustomTemplateDTO>> {
  const resp = await fetch('/ui/templates')
  if (!resp.ok) throw new Error(`GET /ui/templates failed: ${resp.status}`)
  return (await resp.json()) as Record<string, CustomTemplateDTO>
}

export async function saveTemplate(name: string, tpl: CustomTemplateDTO): Promise<void> {
  const resp = await fetch('/ui/templates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, ...tpl }),
  })
  if (!resp.ok) {
    throw new Error(`save template failed: ${resp.status} ${await resp.text()}`)
  }
}

export async function deleteTemplate(name: string): Promise<void> {
  const resp = await fetch(`/ui/templates/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!resp.ok) {
    throw new Error(`delete template failed: ${resp.status} ${await resp.text()}`)
  }
}

// --- S7 就地裁决:选中边上的人侧动作(写权矩阵的 user 行) -----------------

export type HumanVerdict = 'correct' | 'wrong' | 'disputed'

// 人裁决一条 data_flow 边。note 必填——辩护即学习时刻,server 422 兜底。
export async function postVerdict(
  edgeId: string,
  verdict: HumanVerdict,
  note: string,
): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}/verdict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ verdict, note }),
  })
  if (!resp.ok) {
    throw new Error(`verdict failed: ${resp.status} ${await resp.text()}`)
  }
}

// 接受一条 proposed ghost(同意无需辩护;仅人可点)。
export async function acceptGhost(edgeId: string): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}/accept`, {
    method: 'POST',
  })
  if (!resp.ok) {
    throw new Error(`accept failed: ${resp.status} ${await resp.text()}`)
  }
}

// 手动拉边进/出讨论集。
export async function setDiscuss(edgeId: string, discuss: boolean): Promise<void> {
  const resp = await fetch(`/edge/${encodeURIComponent(edgeId)}/discuss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discuss }),
  })
  if (!resp.ok) {
    throw new Error(`discuss failed: ${resp.status} ${await resp.text()}`)
  }
}

// S7 escalate 就地「已处理」:唯一能解除停止信号的人为动作。
export async function resolveNote(nodeId: string, resolveNote?: string): Promise<void> {
  const resp = await fetch(`/node/${encodeURIComponent(nodeId)}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(resolveNote ? { resolve_note: resolveNote } : {}),
  })
  if (!resp.ok) {
    throw new Error(`resolve failed: ${resp.status} ${await resp.text()}`)
  }
}

// --- 跳转并选中原语 + S6 血缘链 ----------------------------------------------

// 选中一个实体先得打开它父容器的视图——这个 slim locator 就是为此。
export interface NodeLocator {
  id: string
  type: string
  name: string
  parent_id: string | null
}

export async function fetchNodeInfo(nodeId: string): Promise<NodeLocator> {
  const resp = await fetch(`/node/${encodeURIComponent(nodeId)}`)
  if (!resp.ok) {
    throw new Error(`GET /node failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as NodeLocator
}

// 血缘链一跳:节点与边分别定级(supports 边是分析者判断、evidence 是机器
// 测量,常不同级——这正是不折叠的理由)。结构跳(parent/plan_file)无边可级。
export interface ProvenanceHop {
  id: string
  type: string
  name: string
  trust: TrustLevel | null
  via_edge: string | null
  via_edge_trust: TrustLevel | null
}

export async function fetchProvenance(nodeId: string): Promise<ProvenanceHop[]> {
  const resp = await fetch(`/node/${encodeURIComponent(nodeId)}/provenance`)
  if (!resp.ok) {
    throw new Error(`GET provenance failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()).chain as ProvenanceHop[]
}

// --- 会话(语言原语):opencode session,agent ops 过 server 写权闸 ---------
// 分歧集端点(/disagreements)保留在后端;前端绑定随「消息类型」功能再回
// 来——框架先行(2026-07-14)。裁决三端点已由上方 S7 就地裁决绑定。

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

// --- S8 provider-neutral sessions ----------------------------------------

export type SessionEventType =
  | 'user_msg'
  | 'agent_text'
  | 'tool_call'
  | 'tool_result'
  | 'status'
  | 'error'

export type ContextRefKind = 'node' | 'edge' | 'port'

export interface ContextRefDTO {
  kind: ContextRefKind
  ref_id: string
}

export type SessionStatusDTO =
  | 'idle'
  | 'running'
  | 'done'
  | 'failed'
  | 'interrupted'
  | 'orphaned'
  | 'native_missing'
  | 'stateless'
  | 'archived'

export interface SessionDTO {
  session_id: string
  provider_id: string
  model: string | null
  native_session_id: string | null
  workspace: string
  parent_session_id: string | null
  forked_from_event_id: string | null
  status: SessionStatusDTO
  legacy: boolean
}

export interface ProviderCapabilitiesDTO {
  native_resume: boolean
  native_fork: boolean
  interrupt: boolean
  tool_events: boolean
  usage: boolean
}

export interface SessionEventDTO {
  type: SessionEventType
  text?: string
  status?: string
  tool_name?: string
  call_id?: string
  input?: unknown
  output?: unknown
  provider_session_id?: string
  details?: Record<string, unknown>
}

export interface ContextPreviewDTO {
  bundle: Record<string, unknown> | null
  payload: {
    instruction: unknown[]
    reference: unknown[]
  }
  sources: Array<{ kind: ContextRefKind; id: string }>
  omissions: Array<Record<string, unknown>>
  delivery: {
    action: 'send' | 'skip'
    reason: string
  }
}

export interface StreamSessionOptions {
  sessionId: string | null
  text: string
  providerId?: string
  model?: string | null
  refs?: ContextRefDTO[]
}

export const DEFAULT_PROVIDER_ID = 'codex'

export async function fetchSessions(): Promise<SessionDTO[]> {
  const resp = await fetch('/session')
  if (!resp.ok) {
    throw new Error(`GET /session failed: ${resp.status} ${await resp.text()}`)
  }
  const payload = (await resp.json()) as { sessions: SessionDTO[] }
  return payload.sessions
}

export async function fetchSessionHistory(
  sessionId: string,
): Promise<{ session: SessionDTO; events: SessionEventDTO[] }> {
  const endpoint = `/session/${encodeURIComponent(sessionId)}/history`
  const resp = await fetch(endpoint)
  if (!resp.ok) {
    throw new Error(`GET ${endpoint} failed: ${resp.status} ${await resp.text()}`)
  }
  const payload = (await resp.json()) as {
    session: SessionDTO
    events: SessionEventDTO[]
  }
  return { session: payload.session, events: payload.events }
}

export async function forkSession(sessionId: string): Promise<SessionDTO> {
  const endpoint = `/session/${encodeURIComponent(sessionId)}/fork`
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  if (!resp.ok) {
    throw new Error(`POST ${endpoint} failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as SessionDTO
}

export async function archiveSession(sessionId: string): Promise<SessionDTO> {
  const endpoint = `/session/${encodeURIComponent(sessionId)}/archive`
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  if (!resp.ok) {
    throw new Error(`POST ${endpoint} failed: ${resp.status} ${await resp.text()}`)
  }
  return (await resp.json()) as SessionDTO
}

export async function previewSessionContext(
  refs: ContextRefDTO[],
  sessionId: string | null = null,
): Promise<ContextPreviewDTO> {
  const body: Record<string, unknown> = { refs }
  if (sessionId) body.session_id = sessionId
  const resp = await fetch('/session/context/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    throw new Error(
      `POST /session/context/preview failed: ${resp.status} ${await resp.text()}`,
    )
  }
  return (await resp.json()) as ContextPreviewDTO
}

export async function streamSessionMessage(
  options: StreamSessionOptions,
  onEvent: (event: SessionEventDTO) => void,
): Promise<string> {
  const initial = options.sessionId === null
  const endpoint = initial
    ? '/session'
    : `/session/${encodeURIComponent(options.sessionId!)}/message`
  const body: Record<string, unknown> = { text: options.text }
  if (initial) {
    body.provider_id = options.providerId ?? DEFAULT_PROVIDER_ID
    if (options.model) body.model = options.model
  }
  if (options.refs && options.refs.length > 0) body.refs = options.refs

  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    throw new Error(`POST ${endpoint} failed: ${resp.status} ${await resp.text()}`)
  }
  if (!resp.body) throw new Error('agent session response has no readable stream')

  let resolvedSessionId =
    options.sessionId ?? resp.headers.get('X-Simulanka-Session-Id')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  while (true) {
    const { done, value } = await reader.read()
    pending += decoder.decode(value, { stream: !done })
    const lines = pending.split('\n')
    pending = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event = JSON.parse(line) as SessionEventDTO
      resolvedSessionId = sessionIdFromCreated(event) ?? resolvedSessionId
      onEvent(event)
    }
    if (done) break
  }
  if (pending.trim()) {
    const event = JSON.parse(pending) as SessionEventDTO
    resolvedSessionId = sessionIdFromCreated(event) ?? resolvedSessionId
    onEvent(event)
  }
  if (!resolvedSessionId) {
    throw new Error('agent session stream did not report a session id')
  }
  return resolvedSessionId
}

function sessionIdFromCreated(event: SessionEventDTO): string | null {
  if (event.type !== 'status' || event.status !== 'created') return null
  const sessionId = event.details?.session_id
  return typeof sessionId === 'string' && sessionId ? sessionId : null
}

// Safety fuse over the server's 180s harness timeout: the UI must never wait
// unbounded — a fuse trip surfaces as an ⚠ bubble in the stream.
const CHAT_TIMEOUT_MS = 200_000

export async function startDiscussion(model?: string): Promise<DiscussionTurn> {
  const resp = await fetch('/discussion/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(model ? { model } : {}),
    signal: AbortSignal.timeout(CHAT_TIMEOUT_MS),
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
    signal: AbortSignal.timeout(CHAT_TIMEOUT_MS),
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
