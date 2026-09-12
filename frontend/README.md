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

## Frontend v2 boundaries

- `src/App.svelte` owns graph loading/navigation, selection, graph actions and
  graph-position persistence. It passes scope changes and **explicit** object refs
  to the Agent controller. Current viewport, neighbours and ancestors are not silently
  injected into Agent context.
- `src/lib/agent-session.ts` owns scope/tree/branch selection, discussion/recovery,
  provider capabilities, streaming, stop/fork/archive, pending explicit refs and
  context preview. It exposes a Svelte store and commands, with no Canvas or
  graph-position dependency. Server persistence and API DTOs remain authoritative.
- `src/lib/AgentCompanion.svelte` is the only default Agent surface. It is a compact
  graph companion, not a permanent chat dock. Explicitly pointing a node/edge/port to
  the Agent opens the small composer; full discussion is mounted only on request.
- `NodeInspector.svelte` treats a node's independent input/output ports as first-class
  interface structure. Zoom may hide labels/card detail on Canvas, but never collapses
  multiple semantic ports into shared anchors.
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

`npm test` covers Session/Context orchestration, including stale asynchronous responses
and scope changes during streaming. It uses the existing Vite TS loader and Node's test
runner, with in-memory Session API fixtures.
