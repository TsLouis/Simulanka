# Simulanka frontend

Svelte + TypeScript + LiteGraph graph-native workspace. Run commands from `frontend/`:

```sh
npm ci
npm run dev
npm test
npm run check
npm run build
```

The development server proxies the existing APIs to `http://127.0.0.1:8765`.
Set `SIMULANKA_API_TARGET` to use a different local backend.

## Frontend v2 model

The product surface is **Graph-native workspace + Agent Companion**, not Graph + Chat UI.
Graph entities are the primary interaction objects; discussions and Session history are
secondary surfaces attached to work on the graph.

For ordinary node-editor interaction, ComfyUI is the baseline reference: independent
ports stay visible, connection anchors remain stable across zoom, datatype is readable
from the link/slot system, and search/selection gestures should follow mature node-editor
conventions unless Simulanka research semantics require a deliberate divergence.

Object-level product language is intentionally small and capability-separated:

- **Ask** adds the exact object Ref to explicit Agent context.
- **Trace** reads deterministic graph provenance/lineage and never invokes the Agent.
  It is only shown where a real system trace resolver exists.
- **Inspect** reveals the object's own interface, attrs and state without mutating the graph.

Node currently uses `Ask / Trace / Inspect`; Edge uses `Ask / Inspect` plus a separate
server-authoritative review layer; Port uses `Ask / Inspect` inside the node interface.

## Frontend v2 boundaries

- `src/lib/WorkspaceShell.svelte` owns the Canvas container and secondary-surface
  visibility. `TopBar.svelte` presents navigation/breadcrumb/status callbacks;
  the 42px `ActivityBar.svelte` opens Inspector, Registry, Files, Discussion and
  Session recovery. Full surfaces start closed; Files reuses the selected file or
  the last explicit file request. Local Inspect/Discussion controls share the same
  open state. These surfaces float over Canvas rather than reserving sidebars.
- `src/App.svelte` owns graph loading/navigation, selection, graph actions and
  graph-position persistence. It passes scope changes and **explicit** object refs
  to the Agent controller. Current viewport, neighbours and ancestors are not silently
  injected into Agent context.
- `src/lib/agent-session.ts` owns scope/tree/branch selection, discussion/recovery,
  provider capabilities, streaming, stop/fork/archive, pending explicit refs and
  context preview. It exposes a Svelte store and commands, with no Canvas or
  graph-position dependency. Server persistence and API DTOs remain authoritative.
- `src/lib/AgentCompanion.svelte` is the only default Agent surface. It is a compact
  graph companion, not a permanent chat dock. The primary pointing gesture is
  **hold `A` → click one or more Node/Port/Edge objects → release `A` → type**.
  Successive clicks accumulate one de-duplicated pending RefSet without moving graph
  objects or stealing focus; releasing `A` focuses the composer when new refs were
  added. Explicit `Ask` actions are the non-keyboard fallback. The abandoned
  drag-to-Pet interaction is intentionally not retained as a second context model.
- `src/lib/agent-projection.ts` validates the latest-turn Conversation Projection.
  Real projection targets must be exact refs delivered in that turn's server-authored
  ContextBundle; prose, selection and viewport never create targets. The current
  graph-chat transport supports strict `attention`, object-specific `annotation` and
  temporary `draft_graph` sidecars and strips the protocol from human-visible text.
- `src/lib/agent-canvas-projection.ts` renders those projections against real Node,
  Port and persisted data-flow Edge geometry. Temporary Draft sketches remain draw-time
  conversation objects and never create semantic Node/Edge/Port entities.
- `NodeInspector.svelte` treats a node's independent input/output ports as first-class
  interface structure. Zoom may hide labels/card detail on Canvas, but never collapses
  multiple semantic ports into shared anchors.
- `src/lib/connection-feedback.ts` filters native LiteGraph 0.7.18 hover highlights
  during real output drags and gives Registry-rejected inputs a muted red native
  Port color. The adapter's pure preview shares `edgeConnectionRejection()` with
  final client validation. Slot types, hit tests, geometry, boundary projection and
  drop behavior stay native; color overrides are restored after every draw.
  Output-only nodes are supported, and orphaned native drag fields are cleared
  after graph replacement so the next frame cannot dereference a removed source.
  Missing descriptors defer to native datatype feedback and server validation.
- Existing proposed Agent graph changes are rendered as `DRAFT` objects. Keep/Dismiss
  product actions continue to map to the authoritative server accept/verdict contracts.
- `SessionHistory.svelte` offers tree/branch selection and lifecycle controls;
  `SessionTranscript.svelte` renders complete normalized events, tool input/output,
  ContextBundle references/audit details and usage. Recovery remains a separate
  read-only view of unassigned sessions.

The legacy floating Session/ChatNode presentation has been removed. Old session-window
coordinates may remain in existing UI-position buckets but are never rendered or
rewritten as session windows.

The Add Node transaction/initial-position correctness bug is tracked separately in #17
and must not be hidden by presentation code.

`npm test` covers native connection feedback, Session/Context orchestration and Conversation Projection safety,
including stale asynchronous Session responses, scope changes during streaming,
latest-turn explicit-ref scoping, invented-target rejection, protocol stripping and
projection fences split across streamed Agent text chunks. Connection tests exercise
LiteGraph 0.7.18 mouse move/up, native Port rendering, boundary-link deletion, and
100 connect/disconnect/graph-replacement cycles without executable graph loops.
Tests use the existing Vite
TS loader and Node's test runner.
