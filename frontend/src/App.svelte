<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte'
  import { LGraphCanvas, type LGraphNode } from 'litegraph.js'
  import 'litegraph.js/css/litegraph.css'
  import {
    createEdge,
    deleteEdge,
    fetchGraph,
    fetchPositions,
    savePositions,
    type Positions,
  } from './lib/api'
  import { subscribeEvents, type EventSubscription } from './lib/events'
  import { buildLiteGraph } from './lib/litegraph-adapter'
  import NodeInspector from './lib/NodeInspector.svelte'
  import type { NodeDTO, PortDTO } from './lib/types'

  let canvasEl: HTMLCanvasElement
  let depth = 1
  let status = 'idle'
  let nodeCount = 0
  let edgeCount = 0
  let boundaryCount = 0
  let liveVersion = -1
  let liveOk = false

  // currentRootId is the single source of truth for navigation. crumbs is
  // derived from payload.ancestors + the active root after each load, so a
  // drill-down or jump-external just sets this and reloads — the breadcrumb
  // trail rebuilds itself with full ancestor info from the server.
  let currentRootId: string | null = null
  let crumbs: { id: string; name: string }[] = []
  let lgcanvas: LGraphCanvas | null = null

  let selectedId: string | null = null
  let selectedNode: NodeDTO | null = null
  let portsById: Map<string, PortDTO> = new Map()

  // Set of node ids currently rendered; used to decide whether an SSE commit
  // is relevant to the active view.
  let currentNodeIds = new Set<string>()

  // Position state is loaded once on mount and kept in memory; node-drag-end
  // mutates this map and POSTs the delta to the backend. positions[rootKey]
  // is the per-view map; rootKey is "top" for top-level, otherwise the root id.
  let positions: Positions = {}
  $: rootKey = currentRootId ?? 'top'
  $: viewPositions = positions[rootKey] ?? {}

  async function load() {
    status = 'loading…'
    try {
      const payload = await fetchGraph(currentRootId, depth)
      const { graph } = buildLiteGraph(payload, {
        onDrillDown: (id) => {
          currentRootId = id
          selectedId = null
          void load()
        },
        onJumpExternal: (id) => {
          currentRootId = id
          selectedId = null
          void load()
        },
        onCreateEdge: async (srcPort, dstPort, shapeCheck) => {
          // System only hints; the human (and later the agent) adjudicate. A
          // shape mismatch is fine when a reshape/flatten/pool sits between the
          // modules — so confirm rather than block.
          if (shapeCheck === 'mismatch') {
            const ok = window.confirm(
              '两端形状对不上 —— 若中间有 reshape/flatten/pool 则正常，否则可能连错。仍要连接吗？',
            )
            if (!ok) return false
          }
          try {
            await createEdge(srcPort, dstPort, shapeCheck)
            return true // SSE commit will reload the view with the persisted edge.
          } catch (err) {
            status = `create edge failed: ${(err as Error).message}`
            return false
          }
        },
        onDeleteEdge: (edgeId) => {
          void deleteEdge(edgeId).catch(err => {
            status = `delete edge failed: ${(err as Error).message}`
          })
        },
      }, viewPositions)
      if (lgcanvas) {
        lgcanvas.setGraph(graph)
      } else {
        lgcanvas = new LGraphCanvas(canvasEl, graph)
        wireSelection(lgcanvas)
        wireNodeMoved(lgcanvas)
        wireGhostLinks(lgcanvas)
      }
      graph.start()
      nodeCount = payload.nodes.length
      edgeCount = payload.edges.length
      boundaryCount = payload.boundary_edges.length
      status = payload.root ? `root=${payload.root}` : 'top-level'

      // Derive breadcrumb from server-provided ancestor chain. The active root
      // becomes the trailing crumb (resolve its name from payload.nodes, where
      // it appears as an included node).
      const activeRoot = payload.root
        ? payload.nodes.find(n => n.id === payload.root)
        : null
      crumbs = activeRoot
        ? [...payload.ancestors.map(a => ({ id: a.id, name: a.name })),
           { id: activeRoot.id, name: activeRoot.name }]
        : []

      portsById = new Map(payload.ports.map(p => [p.id, p]))
      selectedNode = selectedId
        ? payload.nodes.find(n => n.id === selectedId) ?? null
        : null
      if (!selectedNode) selectedId = null

      currentNodeIds = new Set(payload.nodes.map(n => n.id))
    } catch (err) {
      status = `error: ${(err as Error).message}`
    }
  }

  // §13.5.3: render ghost links (agent proposals, status="proposed") dashed.
  // LiteGraph has no per-link dash, so shadow the instance renderLink: set a
  // canvas line-dash around the original draw when the link is flagged ghost.
  // Set once on the canvas; survives setGraph() across reloads.
  function wireGhostLinks(canvas: LGraphCanvas) {
    const proto = (LGraphCanvas.prototype as unknown as {
      renderLink: (...a: unknown[]) => void
    }).renderLink
    ;(canvas as unknown as { renderLink: (...a: unknown[]) => void }).renderLink =
      function (this: unknown, ...args: unknown[]): void {
        const ctx = args[0] as CanvasRenderingContext2D
        const link = args[3] as { simulanka_ghost?: boolean } | undefined
        const ghost = !!link?.simulanka_ghost
        if (ghost) ctx.setLineDash([6, 4])
        // try/finally: if the original renderLink throws, the dash must still be
        // reset, or it leaks onto every later link drawn this frame.
        try {
          proto.apply(this, args)
        } finally {
          if (ghost) ctx.setLineDash([])
        }
      }
  }

  function wireSelection(canvas: LGraphCanvas) {
    // LiteGraph's selection hooks aren't typed in @types/litegraph.js, but the
    // runtime accepts these assignments on LGraphCanvas. Boundary nodes carry
    // a `simulanka_boundary` stash instead of `simulanka`; skip those.
    const c = canvas as unknown as {
      onNodeSelected?: (n: LGraphNode) => void
      onNodeDeselected?: (n: LGraphNode) => void
    }
    c.onNodeSelected = (n: LGraphNode) => {
      const dto = (n as unknown as { simulanka?: NodeDTO }).simulanka
      if (!dto) {
        selectedId = null
        selectedNode = null
        return
      }
      selectedId = dto.id
      selectedNode = dto
    }
    c.onNodeDeselected = () => {
      selectedId = null
      selectedNode = null
    }
  }

  // Pending position deltas, keyed by rootKey. Flushed to the backend on a
  // short debounce so a rapid drag spree fans into one POST.
  let pendingByRoot = new Map<string, Record<string, [number, number]>>()
  let flushTimer: ReturnType<typeof setTimeout> | null = null

  function wireNodeMoved(canvas: LGraphCanvas) {
    // Canvas-level onNodeMoved is the sole capture channel for drags. In
    // litegraph 0.7.18 processMouseUp, a node-drag-release runs the
    // `else if (node_dragged)` branch (which calls onNodeMoved) and never the
    // `else` branch that would call node.onMouseUp — so a per-node onMouseUp
    // backup can't fire on drags (it only fires on a no-move click). Set once
    // on the canvas; it survives setGraph() across reloads.
    const c = canvas as unknown as { onNodeMoved?: (n: LGraphNode) => void }
    c.onNodeMoved = (n: LGraphNode) => {
      const dto = (n as unknown as { simulanka?: NodeDTO }).simulanka
      if (!dto) return
      recordMove(dto.id, Math.round(n.pos[0]), Math.round(n.pos[1]))
    }
  }

  function recordMove(nodeId: string, x: number, y: number) {
    const xy: [number, number] = [x, y]
    const bucket = positions[rootKey] ?? {}
    if (bucket[nodeId] && bucket[nodeId][0] === x && bucket[nodeId][1] === y) {
      // No-op drag (click without movement) — skip the POST.
      return
    }
    bucket[nodeId] = xy
    positions = { ...positions, [rootKey]: bucket }

    const delta = pendingByRoot.get(rootKey) ?? {}
    delta[nodeId] = xy
    pendingByRoot.set(rootKey, delta)
    if (flushTimer) clearTimeout(flushTimer)
    flushTimer = setTimeout(flushPositions, 200)
  }

  async function flushPositions() {
    flushTimer = null
    const snapshot = pendingByRoot
    pendingByRoot = new Map()
    for (const [rk, delta] of snapshot) {
      try {
        await savePositions(rk, delta)
      } catch (err) {
        // Best-effort: log and drop. The next drag will retry; in-memory
        // positions still reflect the user's intent for this session.
        console.error('savePositions failed', err)
      }
    }
  }

  function resizeCanvas() {
    if (!canvasEl) return
    canvasEl.width = canvasEl.clientWidth
    canvasEl.height = canvasEl.clientHeight
    lgcanvas?.draw(true, true)
  }

  function goTo(idx: number) {
    // idx = -1 → top-level; otherwise jump to crumbs[idx] as the new root.
    currentRootId = idx < 0 ? null : crumbs[idx].id
    selectedId = null
    void load()
  }

  let subscription: EventSubscription | null = null

  onMount(async () => {
    try {
      positions = await fetchPositions()
    } catch (err) {
      console.warn('fetchPositions failed; starting with empty layout cache', err)
    }
    void load()
    subscription = subscribeEvents({
      onReady: gv => {
        liveOk = true
        liveVersion = gv
      },
      onCommit: msg => {
        liveOk = true
        liveVersion = msg.graph_version
        // Skip the reload when the commit doesn't touch the active view. At
        // top-level we always reload, because parentless CreateNodeOps don't
        // write a contains edge — msg.nodes would miss them otherwise.
        const touchesView =
          currentRootId === null ||
          msg.nodes.some(id => currentNodeIds.has(id))
        if (touchesView) void load()
      },
      onError: () => {
        liveOk = false
      },
    })
    window.addEventListener('resize', resizeCanvas)
    window.addEventListener('pagehide', beaconFlush)
    document.addEventListener('visibilitychange', flushIfHidden)
  })

  function flushIfHidden() {
    // pagehide is unreliable across browsers; visibilitychange→hidden is the
    // recommended signal to persist before the tab is backgrounded/closed,
    // catching deltas still inside the 200ms debounce window.
    if (document.visibilityState === 'hidden') beaconFlush()
  }

  function beaconFlush() {
    // Page unload: an in-flight fetch may be aborted, so dump pending deltas
    // via sendBeacon which the browser guarantees to dispatch.
    if (flushTimer) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    for (const [rk, delta] of pendingByRoot) {
      const blob = new Blob([JSON.stringify(delta)], { type: 'application/json' })
      navigator.sendBeacon(`/ui/positions/${encodeURIComponent(rk)}`, blob)
    }
    pendingByRoot = new Map()
  }

  onDestroy(() => {
    subscription?.close()
    window.removeEventListener('resize', resizeCanvas)
    window.removeEventListener('pagehide', beaconFlush)
    document.removeEventListener('visibilitychange', flushIfHidden)
    beaconFlush()
  })

  // When the inspector opens/closes the canvas width changes — give the DOM a
  // tick to reflow, then resize the canvas backing buffer to match.
  $: if (selectedNode !== undefined) void tick().then(resizeCanvas)
</script>

<header>
  <strong>Simulanka</strong>
  <nav class="crumbs">
    <button class="crumb" on:click={() => goTo(-1)} class:active={crumbs.length === 0}>
      top
    </button>
    {#each crumbs as c, i}
      <span class="sep">/</span>
      <button
        class="crumb"
        on:click={() => goTo(i)}
        class:active={i === crumbs.length - 1}
        title={c.id}
      >
        {c.name}
      </button>
    {/each}
  </nav>
  <label>depth <input type="number" min="0" max="5" bind:value={depth} on:change={load} /></label>
  <button on:click={load}>Reload</button>
  <span class="status">
    <span class="live" class:on={liveOk} title={liveOk ? `live · v${liveVersion}` : 'disconnected'}></span>
    {status} · {nodeCount}n / {edgeCount}e
    {#if boundaryCount > 0}/ {boundaryCount}↔{/if}
  </span>
</header>

<main class:with-inspector={selectedNode !== null}>
  <canvas bind:this={canvasEl}></canvas>
  <NodeInspector node={selectedNode} {portsById} />
</main>

<style>
  :global(body, html) {
    margin: 0;
    padding: 0;
    background: #1a1a1a;
    color: #ddd;
    font-family: ui-sans-serif, system-ui, sans-serif;
  }
  header {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 8px 12px;
    background: #222;
    border-bottom: 1px solid #333;
    font-size: 13px;
  }
  header input {
    background: #111;
    color: #ddd;
    border: 1px solid #444;
    padding: 2px 6px;
    font-family: inherit;
    font-size: 13px;
  }
  header input[type='number'] {
    width: 50px;
  }
  header button {
    background: #333;
    color: #ddd;
    border: 1px solid #555;
    padding: 3px 10px;
    cursor: pointer;
  }
  header button:hover {
    background: #444;
  }
  .crumbs {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .crumb {
    background: transparent;
    border: none;
    color: #aaa;
    padding: 2px 6px;
    cursor: pointer;
    font: inherit;
  }
  .crumb:hover {
    color: #ddd;
    background: #333;
  }
  .crumb.active {
    color: #fff;
    font-weight: 600;
  }
  .sep {
    color: #555;
  }
  .status {
    margin-left: auto;
    color: #999;
    font-family: ui-monospace, monospace;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .live {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #555;
    transition: background 0.2s;
  }
  .live.on {
    background: #4ade80;
    box-shadow: 0 0 4px #4ade80;
  }
  main {
    display: flex;
    width: 100vw;
    height: calc(100vh - 41px);
  }
  canvas {
    display: block;
    flex: 1;
    min-width: 0;
    height: 100%;
  }
</style>
