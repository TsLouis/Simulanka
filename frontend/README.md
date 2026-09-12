# Simulanka frontend

Svelte + TypeScript + LiteGraph workspace. Run commands from `frontend/`:

```sh
npm ci
npm run dev
npm test
npm run check
npm run build
```

The development server proxies the existing APIs to `http://127.0.0.1:8765`.
Set `SIMULANKA_API_TARGET` to use a different local backend.

## Frontend v2 boundaries

- `src/App.svelte` owns graph loading/navigation, selection, graph actions and
  graph-position persistence. It passes scope changes and explicit object refs
  to the Agent controller.
- `src/lib/agent-session.ts` owns scope/tree/branch selection, history/recovery,
  provider capabilities, streaming, stop/fork/archive, pending explicit refs and
  context preview. It exposes a Svelte store and commands, with no Canvas or
  graph-position dependency. Server persistence and API DTOs remain authoritative.
- `src/lib/AgentCompanion.svelte` is the only default Agent surface. Its compact
  composer opens on request or explicit attachment. History is mounted only when
  requested; closing it does not stop the controller's stream.
- `SessionHistory.svelte` offers tree/branch selection and lifecycle controls;
  `SessionTranscript.svelte` renders complete normalized events, tool input/output,
  ContextBundle references/audit details and usage. Recovery is available through
  History and remains a separate read-only view of unassigned sessions.

The cleanup does not migrate persisted data. Old session-window coordinates may
remain in existing UI-position buckets but are never rendered or rewritten as
session windows. The Add Node transaction/initial-position bug is tracked in #17
and is outside this cleanup.

`npm test` covers Session/Context orchestration, including stale asynchronous
responses and scope changes during streaming. It uses the existing Vite TS loader
and Node's test runner, with in-memory Session API fixtures.
