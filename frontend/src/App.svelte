<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  // No litegraph.css: it only styles LiteGraph's DOM widgets (context menu,
  // searchbox, dialogs), all of which we disabled in favour of our own chrome.
  import { LGraphCanvas, type LGraphNode } from 'litegraph.js'
  import {
    createEdge,
    createNode,
    deleteEdge,
    deleteNode,
    deleteTemplate,
    fetchDiscussionState,
    fetchGraph,
    fetchPositions,
    fetchTemplates,
    renameNode,
    savePositions,
    saveTemplate,
    sendDiscussionMessage,
    startDiscussion,
    type CustomTemplateDTO,
    type DiscussionTurn,
    type FileOpenRequest,
    type Positions,
  } from './lib/api'
  import { subscribeEvents, type EventSubscription } from './lib/events'
  import { buildLiteGraph } from './lib/litegraph-adapter'
  import { buildGroups, type NodeTemplate } from './lib/templates'
  import { applyNightSky } from './lib/theme'
  import ChatDock from './lib/ChatDock.svelte'
  import ChatNode, { type ChatMsg } from './lib/ChatNode.svelte'
  import ContextMenu from './lib/ContextMenu.svelte'
  import FileViewer from './lib/FileViewer.svelte'
  import NodeInspector from './lib/NodeInspector.svelte'
  import type { NodeDTO, PortDTO } from './lib/types'

  let canvasEl: HTMLCanvasElement
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

  // S4 file viewer: non-null = the drawer is open on this request. Assigning a
  // new request re-loads in place (e.g. jumping 出处 from another atom).
  let fileRequest: FileOpenRequest | null = null

  // Right-click menu: non-null = open. graphPos is where the click landed in
  // graph coordinates — a node added from the menu drops exactly there.
  let menu: {
    x: number
    y: number
    mode: 'add' | 'node'
    node: NodeDTO | null
    graphPos: [number, number]
  } | null = null
  let customTemplates: Record<string, CustomTemplateDTO> = {}
  // Type of the container the view is inside (null = top-level). The add-node
  // menu only offers templates the kernel's containment matrix would accept
  // here — torch modules inside model/module, containers inside directories.
  let currentRootType: string | null = null
  $: templateGroups = buildGroups(customTemplates, currentRootType)

  // Message surface state: chatPanelOpen = the floating 会话节点 is visible;
  // the dock toggles it and an incoming turn opens it.
  let chatPanelOpen = false

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
      const payload = await fetchGraph(currentRootId)
      const { graph } = buildLiteGraph(payload, {
        onDrillDown: (id) => navigateTo(id),
        onJumpExternal: (id) => navigateTo(id),
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
        applyNightSky(lgcanvas)
        wireSelection(lgcanvas)
        wireNodeMoved(lgcanvas)
        wireGhostLinks(lgcanvas)
        wireContextMenu(lgcanvas)
      }
      graph.start()
      nodeCount = payload.nodes.length
      edgeCount = payload.edges.length
      boundaryCount = payload.boundary_edges.length
      status = payload.root ? `root=${payload.root}` : 'top-level'

      // Derive breadcrumb from server-provided ancestor chain; the active root
      // (root_info) becomes the trailing crumb. The root never appears among
      // payload.nodes — the canvas is the inside of the container, not the
      // container plus its children.
      crumbs = payload.root_info
        ? [...payload.ancestors.map(a => ({ id: a.id, name: a.name })),
           { id: payload.root_info.id, name: payload.root_info.name }]
        : []
      currentRootType = payload.root_info?.type ?? null

      portsById = new Map(payload.ports.map(p => [p.id, p]))
      selectedNode = selectedId
        ? payload.nodes.find(n => n.id === selectedId) ?? null
        : null
      if (!selectedNode) selectedId = null

      // Root included: a commit touching the container itself (rename, an
      // edge from its ports to a child) must refresh this view too.
      currentNodeIds = new Set(payload.nodes.map(n => n.id))
      if (payload.root) currentNodeIds.add(payload.root)
    } catch (err) {
      status = `error: ${(err as Error).message}`
    }
  }

  // §13.6 discussion chat state. Lives here, not in the panel: closing the
  // panel must not drop the thread. Applied ops come back over SSE like any
  // other kernel commit — no manual canvas refresh needed.
  let chatMessages: ChatMsg[] = []
  let chatBusy = false
  let discussionActive = false

  function chatTurn(turn: DiscussionTurn) {
    chatMessages = [
      ...chatMessages,
      { role: 'agent', text: turn.reply, applied: turn.applied, rejected: turn.rejected },
    ]
    chatPanelOpen = true
    if (turn.op_errors.length > 0) {
      status = `agent op-block errors: ${turn.op_errors.join('; ')}`
    }
  }

  // 锚定标签(§13.6):选中集优先,否则当前容器。随消息一起送给 agent,
  // 也显示在 dock 上——人和 agent 对「在谈什么」保持同一认知。
  $: anchorLabel = selectedNode
    ? `${selectedNode.type}:${selectedNode.name}`
    : crumbs.length > 0
      ? `容器:${crumbs[crumbs.length - 1].name}`
      : '全图'

  // One send path: first message auto-starts the opencode session (the
  // opening turn snapshots the disagreement set server-side), then the text
  // goes out with its anchor stamped in front.
  async function chatSend(text: string) {
    const stamped = `（锚定：${anchorLabel}）\n${text}`
    chatMessages = [...chatMessages, { role: 'user', text }]
    chatPanelOpen = true
    chatBusy = true
    try {
      if (!discussionActive) {
        const opening = await startDiscussion()
        discussionActive = true
        chatTurn(opening)
      }
      chatTurn(await sendDiscussionMessage(stamped))
    } catch (err) {
      // Failures land in the stream itself — a status-bar whisper reads as a
      // dead click (彩排实测: user perceived it as a freeze).
      chatMessages = [
        ...chatMessages,
        { role: 'agent', text: `⚠ 会话失败: ${(err as Error).message}` },
      ]
    } finally {
      chatBusy = false
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
        const link = args[3] as
          | {
              simulanka_ghost?: boolean
              simulanka_slice?: string
              _pos?: [number, number]
              color?: string
            }
          | undefined
        const ghost = !!link?.simulanka_ghost
        if (ghost) ctx.setLineDash([6, 4])
        // try/finally: if the original renderLink throws, the dash must still be
        // reset, or it leaks onto every later link drawn this frame.
        try {
          proto.apply(this, args)
        } finally {
          if (ghost) ctx.setLineDash([])
        }
        // §13.5.6: after the line (dash already reset), tag the slice this edge
        // carries at the link centre — renderLink populated link._pos. Two edges
        // from one output port then read apart by their slice, not just target.
        const slice = link?.simulanka_slice
        if (slice && link?._pos) {
          drawSliceLabel(ctx, link._pos, slice, link.color ?? '#b28ce0')
        }
      }
  }

  // A small chip at the link centre carrying the output-slice (§13.5.6). Drawn
  // in graph coordinates (the renderLink ctx is already canvas-transformed).
  // 星图册: night-lacquer chip, hairline border in the link's own colour.
  function drawSliceLabel(
    ctx: CanvasRenderingContext2D,
    pos: [number, number],
    text: string,
    color: string,
  ) {
    ctx.save()
    ctx.font = '10px ui-monospace, monospace'
    const w = ctx.measureText(text).width
    const padX = 5
    const h = 14
    const x = pos[0] - w / 2 - padX
    const y = pos[1] - h / 2
    const bw = w + padX * 2
    const r = 4
    ctx.beginPath()
    ctx.roundRect(x, y, bw, h, r)
    ctx.fillStyle = 'rgba(11, 19, 34, 0.88)' // --sky @ 88%
    ctx.fill()
    ctx.strokeStyle = color
    ctx.globalAlpha = 0.55
    ctx.lineWidth = 1
    ctx.stroke()
    ctx.globalAlpha = 1
    ctx.fillStyle = color
    ctx.textBaseline = 'middle'
    ctx.fillText(text, pos[0] - w / 2, pos[1])
    ctx.restore()
  }

  // Right-click is ours: LiteGraph's built-in context menu (and its dbl-click
  // searchbox) list internal registered type names and create canvas-only
  // phantom nodes that never enter the graph. Neutralise both and route the
  // DOM contextmenu event to our own menu, which persists through the kernel.
  function wireContextMenu(canvas: LGraphCanvas) {
    ;(canvas as unknown as { processContextMenu: () => void }).processContextMenu =
      () => {}
    ;(canvas as unknown as { allow_searchbox: boolean }).allow_searchbox = false
    // Delete/Backspace: LiteGraph's own deleteSelectedNodes removes nodes from
    // the canvas only — a phantom delete that lies about graph state and
    // resurrects on reload. Route it through the kernel instead.
    ;(canvas as unknown as { deleteSelectedNodes: () => void }).deleteSelectedNodes =
      () => {
        const sel = (canvas as unknown as {
          selected_nodes?: Record<string, LGraphNode>
        }).selected_nodes
        if (!sel) return
        for (const key of Object.keys(sel)) {
          const dto = (sel[key] as unknown as { simulanka?: NodeDTO }).simulanka
          if (dto) requestDeleteNode(dto)
        }
      }
    canvasEl.addEventListener('contextmenu', onCanvasContextMenu)
  }

  function onCanvasContextMenu(e: MouseEvent) {
    e.preventDefault()
    if (!lgcanvas) return
    const pos = (lgcanvas as unknown as {
      convertEventToCanvasOffset: (e: MouseEvent) => [number, number]
    }).convertEventToCanvasOffset(e)
    const g = lgcanvas.graph as unknown as {
      getNodeOnPos?: (x: number, y: number) => LGraphNode | null
    } | null
    const hit = g?.getNodeOnPos?.(pos[0], pos[1]) ?? null
    // Boundary stubs carry no `simulanka` DTO — treat them like empty canvas.
    const dto = hit ? ((hit as unknown as { simulanka?: NodeDTO }).simulanka ?? null) : null
    menu = {
      x: e.clientX,
      y: e.clientY,
      mode: dto ? 'node' : 'add',
      node: dto,
      graphPos: [Math.round(pos[0]), Math.round(pos[1])],
    }
  }

  async function menuAddNode(t: NodeTemplate) {
    const at = menu?.graphPos ?? [120, 120]
    menu = null
    try {
      const res = await createNode({
        type: t.type,
        name: t.name,
        parent: currentRootId,
        attrs: t.attrs,
        ports: t.ports,
      })
      // Drop the node where the user clicked: record the position before the
      // SSE-triggered reload, so dagre doesn't fling it elsewhere.
      recordMove(res.node_id, at[0], at[1])
    } catch (err) {
      status = `add node failed: ${(err as Error).message}`
    }
  }

  function menuEnter() {
    if (!menu?.node) return
    const id = menu.node.id
    menu = null
    navigateTo(id)
  }

  async function menuRename() {
    if (!menu?.node) return
    const n = menu.node
    menu = null
    const newName = window.prompt('新名字', n.name)
    if (!newName || !newName.trim() || newName.trim() === n.name) return
    try {
      await renameNode(n.id, newName.trim())
    } catch (err) {
      status = `rename failed: ${(err as Error).message}`
    }
  }

  async function menuSaveTemplate() {
    if (!menu?.node) return
    const n = menu.node
    menu = null
    const name = window.prompt('模板名', n.name)
    if (!name || !name.trim()) return
    // Instance-specific importer stamps don't belong in a reusable template.
    const attrs = { ...n.attrs }
    delete attrs.fqn
    delete attrs.num_params
    delete attrs.source_file
    const ports = n.ports
      .map(pid => portsById.get(pid))
      .filter((p): p is PortDTO => !!p)
      .map(p => ({ name: p.name, direction: p.side, port_type: p.port_type }))
    try {
      await saveTemplate(name.trim(), { category: 'custom', type: n.type, attrs, ports })
      customTemplates = await fetchTemplates()
      status = `模板已存: ${name.trim()}`
    } catch (err) {
      status = `save template failed: ${(err as Error).message}`
    }
  }

  // One deletion path for menu and Delete key alike: the kernel decides, the
  // canvas never forks from graph state. Refusals (non-empty, out-of-domain)
  // surface in the status bar; success comes back over SSE.
  function requestDeleteNode(dto: NodeDTO) {
    void deleteNode(dto.id).catch(err => {
      status = `delete failed: ${(err as Error).message}`
    })
  }

  function menuDelete() {
    if (!menu?.node) return
    const n = menu.node
    menu = null
    requestDeleteNode(n)
  }

  async function menuDeleteTemplate(name: string) {
    // Menu stays open — the groups prop refreshes reactively.
    try {
      await deleteTemplate(name)
      customTemplates = await fetchTemplates()
    } catch (err) {
      status = `delete template failed: ${(err as Error).message}`
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

  // Browser-like view history: every navigation (drill-down, jump, crumb)
  // goes through navigateTo, so mouse back/forward buttons and Alt+arrows
  // walk the trail. SSE reloads keep the current root and don't touch it.
  let navBack: (string | null)[] = []
  let navFwd: (string | null)[] = []

  function navigateTo(root: string | null) {
    if (root === currentRootId) return
    navBack = [...navBack, currentRootId]
    navFwd = []
    currentRootId = root
    selectedId = null
    void load()
  }

  function goBack() {
    if (navBack.length === 0) return
    navFwd = [...navFwd, currentRootId]
    currentRootId = navBack[navBack.length - 1]
    navBack = navBack.slice(0, -1)
    selectedId = null
    void load()
  }

  function goForward() {
    if (navFwd.length === 0) return
    navBack = [...navBack, currentRootId]
    currentRootId = navFwd[navFwd.length - 1]
    navFwd = navFwd.slice(0, -1)
    selectedId = null
    void load()
  }

  // Mouse side buttons (3=back, 4=forward) and Alt+←/→.
  function onNavMouse(e: MouseEvent) {
    if (e.button === 3) {
      e.preventDefault()
      goBack()
    } else if (e.button === 4) {
      e.preventDefault()
      goForward()
    }
  }
  function onNavKey(e: KeyboardEvent) {
    if (!e.altKey) return
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      goBack()
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      goForward()
    }
  }

  function goTo(idx: number) {
    // idx = -1 → top-level; otherwise jump to crumbs[idx] as the new root.
    navigateTo(idx < 0 ? null : crumbs[idx].id)
  }

  let subscription: EventSubscription | null = null

  onMount(async () => {
    try {
      positions = await fetchPositions()
    } catch (err) {
      console.warn('fetchPositions failed; starting with empty layout cache', err)
    }
    void fetchTemplates()
      .then(t => {
        customTemplates = t
      })
      .catch(() => undefined)
    // An opencode session survives a page reload (state file + session id);
    // history doesn't — the transcript lives in the session, not the server.
    void fetchDiscussionState()
      .then(s => {
        discussionActive = s.active
      })
      .catch(() => undefined)
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
        if (touchesView) {
          void load()
        }
      },
      onError: () => {
        liveOk = false
      },
    })
    window.addEventListener('resize', resizeCanvas)
    window.addEventListener('pagehide', beaconFlush)
    window.addEventListener('mouseup', onNavMouse)
    window.addEventListener('keydown', onNavKey)
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
    canvasEl?.removeEventListener('contextmenu', onCanvasContextMenu)
    window.removeEventListener('resize', resizeCanvas)
    window.removeEventListener('pagehide', beaconFlush)
    window.removeEventListener('mouseup', onNavMouse)
    window.removeEventListener('keydown', onNavKey)
    document.removeEventListener('visibilitychange', flushIfHidden)
    beaconFlush()
  })

  // When the inspector opens/closes the canvas width changes — resize the
  // canvas backing buffer after the DOM settles. queueMicrotask, NOT tick():
  // Svelte 5's tick() flushSyncs, and calling it from a legacy `$:` re-enters
  // the flush loop forever (the ChatNode freeze had exactly this shape).
  $: if (selectedNode !== undefined) queueMicrotask(resizeCanvas)
</script>

<header>
  <strong class="brand"><span class="brand-star">✦</span>Simulanka</strong>
  <span class="nav-btns">
    <button on:click={goBack} disabled={navBack.length === 0} title="后退(Alt+← / 鼠标侧键)">‹</button>
    <button on:click={goForward} disabled={navFwd.length === 0} title="前进(Alt+→ / 鼠标侧键)">›</button>
  </span>
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
  <button on:click={load}>Reload</button>
  <span class="status">
    <span class="live" class:on={liveOk} title={liveOk ? `live · v${liveVersion}` : 'disconnected'}></span>
    {status} · {nodeCount}n / {edgeCount}e
    {#if boundaryCount > 0}/ {boundaryCount}↔{/if}
  </span>
</header>

<main class:with-inspector={selectedNode !== null}>
  <canvas bind:this={canvasEl}></canvas>
  <NodeInspector
    node={selectedNode}
    {portsById}
    onOpenFile={(req) => (fileRequest = req)}
  />
  {#if fileRequest}
    <FileViewer request={fileRequest} onClose={() => (fileRequest = null)} />
  {/if}
  {#if menu}
    <ContextMenu
      x={menu.x}
      y={menu.y}
      mode={menu.mode}
      node={menu.node}
      groups={templateGroups}
      onClose={() => (menu = null)}
      onPick={menuAddNode}
      onEnter={menuEnter}
      onRename={menuRename}
      onSaveTemplate={menuSaveTemplate}
      onDelete={menuDelete}
      onDeleteTemplate={menuDeleteTemplate}
    />
  {/if}
  <ChatDock
    {anchorLabel}
    busy={chatBusy}
    panelOpen={chatPanelOpen}
    onSend={t => void chatSend(t)}
    onTogglePanel={() => (chatPanelOpen = !chatPanelOpen)}
  />
  {#if chatPanelOpen}
    <ChatNode
      messages={chatMessages}
      active={discussionActive}
      busy={chatBusy}
      onClose={() => (chatPanelOpen = false)}
    />
  {/if}
</main>

<style>
  /* 星图册壳层：漆器顶栏 + 金缘 + 夜空画布。调色板见 app.css :root。 */
  header {
    position: relative;
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 9px 16px;
    background: linear-gradient(180deg, #1a2642 0%, #141e36 100%);
    font-size: 13px;
  }
  /* 顶栏下缘的一线金 —— 两端隐入夜色 */
  header::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 1px;
    background: linear-gradient(
      90deg,
      transparent 0%,
      var(--gold-dim) 12%,
      var(--gold) 50%,
      var(--gold-dim) 88%,
      transparent 100%
    );
  }
  .brand {
    font-family: var(--font-display);
    font-size: 19px;
    font-weight: 400;
    letter-spacing: 0.08em;
    color: var(--gold-bright);
    text-shadow: 0 0 14px var(--gold-glow);
    display: flex;
    align-items: baseline;
    gap: 7px;
    user-select: none;
  }
  .brand-star {
    font-size: 13px;
    color: var(--gold);
    animation: star-breathe 4s ease-in-out infinite;
  }
  @keyframes star-breathe {
    0%,
    100% {
      opacity: 0.65;
      text-shadow: 0 0 4px var(--gold-glow);
    }
    50% {
      opacity: 1;
      text-shadow: 0 0 12px var(--gold-glow);
    }
  }
  header button {
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 4px;
    padding: 4px 12px;
    cursor: pointer;
    font-family: inherit;
    transition:
      border-color 0.15s,
      color 0.15s,
      box-shadow 0.15s;
  }
  header button:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  .nav-btns {
    display: flex;
    gap: 4px;
  }
  .nav-btns button {
    padding: 2px 9px;
    font-size: 15px;
    line-height: 1;
  }
  .nav-btns button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .crumbs {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .crumb {
    background: transparent;
    border: none;
    color: var(--muted);
    padding: 2px 7px;
    border-radius: 4px;
    cursor: pointer;
    font: inherit;
    transition:
      color 0.15s,
      background 0.15s;
  }
  .crumb:hover {
    color: var(--ivory);
    background: var(--panel-2);
  }
  .crumb.active {
    color: var(--gold-bright);
    font-weight: 500;
  }
  .sep {
    color: var(--gold-dim);
    font-size: 11px;
  }
  .status {
    margin-left: auto;
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .live {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3a4763;
    transition: background 0.2s;
  }
  .live.on {
    background: var(--jade);
    box-shadow: 0 0 6px rgba(126, 207, 165, 0.8);
  }
  main {
    display: flex;
    width: 100vw;
    height: calc(100vh - 44px);
    /* FileViewer 抽屉以此为定位容器（position: absolute; right: 0） */
    position: relative;
  }
  canvas {
    display: block;
    flex: 1;
    min-width: 0;
    height: 100%;
    background: var(--sky);
    animation: sky-reveal 0.9s ease-out;
  }
  /* 开场：夜空自深处浮现一次，不循环不打扰 */
  @keyframes sky-reveal {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
</style>
