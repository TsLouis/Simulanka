<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  // No litegraph.css: it only styles LiteGraph's DOM widgets (context menu,
  // searchbox, dialogs), all of which we disabled in favour of our own chrome.
  import { LGraphCanvas, type LGraphNode } from 'litegraph.js'
  import {
    acceptGhost,
    createEdge,
    createNode,
    deleteEdge,
    deleteNode,
    deleteTemplate,
    fetchGraph,
    getCachedRegistryDescriptor,
    fetchNodeInfo,
    fetchPositions,
    fetchTemplates,
    postVerdict,
    renameNode,
    resolveAffordances,
    resolveNote,
    savePositions,
    saveTemplate,
    setDiscuss,
    type CustomTemplateDTO,
    type FileOpenRequest,
    type HumanVerdict,
    type Positions,
  } from './lib/api'
  import { subscribeEvents, type EventSubscription } from './lib/events'
  import { buildLiteGraph, type LineageEdge } from './lib/litegraph-adapter'
  import { buildGroups, type NodeTemplate } from './lib/templates'
  import { applyWorkspaceTheme, LINEAGE_COLOR } from './lib/theme'
  import AgentCompanion from './lib/AgentCompanion.svelte'
  import { createAgentSessionController } from './lib/agent-session'
  import ContextMenu from './lib/ContextMenu.svelte'
  import EdgeMenu from './lib/EdgeMenu.svelte'
  import FileViewer from './lib/FileViewer.svelte'
  import NodeInspector from './lib/NodeInspector.svelte'
  import RegistryPanel from './lib/RegistryPanel.svelte'
  import type {
    AffordanceDTO,
    EdgeDTO,
    NodeDTO,
    PortDTO,
    RegistryDescriptorDTO,
  } from './lib/types'

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

  // 跳转并选中原语（S6 血缘链逐跳 / S7 卡片点击共用）：先问 locator 拿父容器，
  // 视图到位后在 load() 末尾兑现选中——跨下钻层级可达。
  let byNodeMap: Map<string, LGraphNode> = new Map()
  let lineageEdges: LineageEdge[] = []
  let pendingSelectId: string | null = null

  // S7 就地裁决：当前视图的边 DTO 与端点名字表；edgeMenu 非空 = 菜单开着。
  let edgesById: Map<string, EdgeDTO> = new Map()
  let namesById: Map<string, string> = new Map()
  let edgeMenu: { x: number; y: number; edge: EdgeDTO } | null = null

  // S4 file viewer: non-null = the drawer is open on this request. Assigning a
  // new request re-loads in place (e.g. jumping 出处 from another atom).
  let fileRequest: FileOpenRequest | null = null

  // Right-click menu: non-null = open. graphPos is where the click landed in
  // graph coordinates — a node added from the menu drops exactly there.
  let menu: {
    x: number
    y: number
    mode: 'add' | 'node'
    nodes: NodeDTO[]
    affordances: AffordanceDTO[]
    graphPos: [number, number]
  } | null = null
  let customTemplates: Record<string, CustomTemplateDTO> = {}
  let registryDescriptor: RegistryDescriptorDTO | null = null
  let registryOpen = false
  let createAffordance: AffordanceDTO | null = null
  // Type of the container the view is inside (null = top-level). The add-node
  // menu filters server-described Profiles/Templates against the resolved
  // parent rule; server/kernel remain the final authority.
  let currentRootType: string | null = null
  $: templateGroups = buildGroups(
    registryDescriptor,
    customTemplates,
    currentRootType,
    createAffordance,
  )

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
    createAffordance = null
    try {
      const payload = await fetchGraph(currentRootId)
      registryDescriptor = getCachedRegistryDescriptor()
      createAffordance = (
        payload.root_info?.affordances ?? payload.view_affordances
      ).find(action => action.id === 'node.create') ?? null
      const { graph, byNode, lineage } = buildLiteGraph(payload, {
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
        onConnectionRejected: (reason) => {
          status = `连接已拦截：${reason}`
        },
      }, viewPositions, registryDescriptor)
      if (lgcanvas) {
        lgcanvas.setGraph(graph)
      } else {
        lgcanvas = new LGraphCanvas(canvasEl, graph)
        applyWorkspaceTheme(lgcanvas)
        wireSelection(lgcanvas)
        wireNodeMoved(lgcanvas)
        wireGhostLinks(lgcanvas)
        wireContextMenu(lgcanvas)
        wireLinkMenu(lgcanvas)
        wireLineageLayer(lgcanvas)
      }
      graph.start()
      byNodeMap = byNode
      lineageEdges = lineage
      edgesById = new Map(
        [...payload.edges, ...payload.boundary_edges].map(e => [e.id, e]),
      )
      namesById = new Map([
        ...payload.nodes.map(n => [n.id, n.name] as [string, string]),
        ...payload.external_nodes.map(n => [n.id, n.name] as [string, string]),
        ...(payload.root_info ? [[payload.root_info.id, payload.root_info.name] as [string, string]] : []),
      ])
      // 视图刷新后旧边菜单可能指着已变/已删的边——保守收起。
      edgeMenu = null
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

      applyPendingSelect()
    } catch (err) {
      status = `error: ${(err as Error).message}`
    }
  }

  // --- 跳转并选中（S6/S7 共用原语） -----------------------------------------

  async function jumpToEntity(id: string) {
    try {
      const info = await fetchNodeInfo(id)
      pendingSelectId = id
      if (info.parent_id !== currentRootId) {
        navigateTo(info.parent_id)
      } else {
        applyPendingSelect()
      }
    } catch (err) {
      status = `跳转失败: ${(err as Error).message}`
    }
  }

  function applyPendingSelect() {
    if (!pendingSelectId || !lgcanvas) return
    const ln = byNodeMap.get(pendingSelectId)
    pendingSelectId = null
    if (!ln) return
    const c = lgcanvas as unknown as {
      selectNodes?: (ns: LGraphNode[]) => void
      centerOnNode?: (n: LGraphNode) => void
    }
    c.selectNodes?.([ln])
    c.centerOnNode?.(ln)
    const dto = (ln as unknown as { simulanka?: NodeDTO }).simulanka
    if (dto) {
      selectedId = dto.id
      selectedNode = dto
    }
  }

  // --- S7 就地裁决：链接中心点点击 → 锚定菜单 → server 人侧端点 --------------

  // LiteGraph 原生把「点中链接中心点」路由到 showLinkMenu(默认弹它自己的
  // 菜单)——覆写成我们的锚定菜单。设一次即可,随 setGraph 存活。
  function wireLinkMenu(canvas: LGraphCanvas) {
    ;(canvas as unknown as {
      showLinkMenu: (link: unknown, e: MouseEvent) => void
    }).showLinkMenu = (link, e) => {
      const id = (link as { simulanka_edge_id?: string }).simulanka_edge_id
      const dto = id ? edgesById.get(id) : undefined
      if (!dto) return
      edgeMenu = { x: e.clientX, y: e.clientY, edge: dto }
    }
  }

  async function edgeVerdict(edge: EdgeDTO, verdict: HumanVerdict) {
    edgeMenu = null
    // note 必填——辩护即学习时刻(§13.6);取消 prompt = 放弃裁决。
    const note = window.prompt('辩护理由（必填）：我认为…因为…')
    if (note === null) return
    if (!note.trim()) {
      status = '裁决需要理由 —— 未提交'
      return
    }
    try {
      await postVerdict(edge.id, verdict, note.trim())
    } catch (err) {
      status = `verdict failed: ${(err as Error).message}`
    }
  }

  async function edgeAccept(edge: EdgeDTO) {
    edgeMenu = null
    try {
      await acceptGhost(edge.id)
    } catch (err) {
      status = `accept failed: ${(err as Error).message}`
    }
  }

  async function edgeToggleDiscuss(edge: EdgeDTO) {
    edgeMenu = null
    try {
      await setDiscuss(edge.id, edge.attrs.discuss !== true)
    } catch (err) {
      status = `discuss failed: ${(err as Error).message}`
    }
  }

  // S7 escalate 就地「已处理」:唯一能解除停止信号的人为动作(取消 = 不动)。
  async function resolveEscalate(nodeId: string) {
    const note = window.prompt('处理说明（可选，留空跳过）', '')
    if (note === null) return
    try {
      await resolveNote(nodeId, note.trim() || undefined)
    } catch (err) {
      status = `resolve failed: ${(err as Error).message}`
    }
  }

  const agent = createAgentSessionController()

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
  // The chip border uses the link's own colour.
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
    ctx.fillStyle = 'rgba(11, 19, 34, 0.88)' // --canvas-bg @ 88%
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
        const nodes = Object.values(sel)
          .map(selected => (selected as unknown as { simulanka?: NodeDTO }).simulanka)
          .filter((dto): dto is NodeDTO => dto !== undefined)
        void deleteSelectedNodes(nodes)
      }
    canvasEl.addEventListener('contextmenu', onCanvasContextMenu)
  }

  async function onCanvasContextMenu(e: MouseEvent) {
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
    const selected = (lgcanvas as unknown as {
      selected_nodes?: Record<string, LGraphNode>
    }).selected_nodes
    const selectedDtos = Object.values(selected ?? {})
      .map(selectedNode => (selectedNode as unknown as { simulanka?: NodeDTO }).simulanka)
      .filter((item): item is NodeDTO => item !== undefined)
    const nodes = dto && selectedDtos.some(item => item.id === dto.id) && selectedDtos.length > 1
      ? selectedDtos
      : dto
        ? [dto]
        : []
    let affordances = dto?.affordances ?? []
    if (nodes.length > 1) {
      try {
        affordances = await resolveAffordances(
          nodes.map(node => ({ kind: 'node', id: node.id })),
        )
      } catch (err) {
        status = `resolve actions failed: ${(err as Error).message}`
        return
      }
    }
    menu = {
      x: e.clientX,
      y: e.clientY,
      mode: dto ? 'node' : 'add',
      nodes,
      affordances,
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
    const node = menu?.nodes[0]
    if (!node) return
    const id = node.id
    menu = null
    navigateTo(id)
  }

  async function menuCreateChild() {
    const target = menu?.nodes[0]
    if (!target || !menu) return
    const anchor = { x: menu.x, y: menu.y }
    menu = null
    navBack = [...navBack, currentRootId]
    navFwd = []
    currentRootId = target.id
    selectedId = null
    await agent.setScope(target.id)
    await load()
    menu = {
      ...anchor,
      mode: 'add',
      nodes: [],
      affordances: [],
      graphPos: [120, 120],
    }
  }

  async function menuRename() {
    const n = menu?.nodes[0]
    if (!n) return
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
    const n = menu?.nodes[0]
    if (!n) return
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

  async function deleteSelectedNodes(nodes: NodeDTO[]) {
    if (nodes.length === 0) return
    let affordances = nodes[0].affordances
    if (nodes.length > 1) {
      try {
        affordances = await resolveAffordances(
          nodes.map(node => ({ kind: 'node', id: node.id })),
        )
      } catch (err) {
        status = `resolve delete failed: ${(err as Error).message}`
        return
      }
    }
    const action = affordances.find(item => item.id === 'node.delete')
    if (!action?.enabled) {
      status = action?.reason ?? '所选节点当前不可删除'
      return
    }
    for (const node of nodes) {
      try {
        await deleteNode(node.id)
      } catch (err) {
        status = `delete failed: ${(err as Error).message}`
        return
      }
    }
  }

  function menuDelete() {
    const nodes = menu?.nodes ?? []
    menu = null
    void deleteSelectedNodes(nodes)
  }

  function menuAttach() {
    const nodes = menu?.nodes ?? []
    for (const node of nodes) {
      agent.addPendingRef(
        { kind: 'node', ref_id: node.id },
        `${node.type} · ${node.name}`,
      )
    }
    menu = null
  }

  function menuAction(action: AffordanceDTO) {
    if (!action.enabled) {
      status = action.reason
      return
    }
    switch (action.id) {
      case 'node.create':
        void menuCreateChild()
        break
      case 'node.enter':
        menuEnter()
        break
      case 'node.rename':
        void menuRename()
        break
      case 'node.delete':
        menuDelete()
        break
      case 'context.attach':
        menuAttach()
        break
      case 'template.save':
        void menuSaveTemplate()
        break
      default:
        status = `unsupported action: ${action.id}`
    }
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

  // 血缘丝线层：无端口的语义边（fulfills/produces/…）画在节点层之下——
  // LiteGraph 的连线要插槽，这些边没有，adapter 收集后由这里手绘。
  // 每帧从节点实时位置取端点，拖动节点丝线自然跟随。
  function wireLineageLayer(canvas: LGraphCanvas) {
    ;(canvas as unknown as {
      onDrawBackground: (ctx: CanvasRenderingContext2D) => void
    }).onDrawBackground = (ctx: CanvasRenderingContext2D) => {
      if (lineageEdges.length === 0) return
      ctx.save()
      ctx.setLineDash([7, 5])
      ctx.lineWidth = 1.5
      ctx.strokeStyle = LINEAGE_COLOR
      ctx.fillStyle = LINEAGE_COLOR
      ctx.font = '11px "Noto Sans SC", sans-serif'
      ctx.textAlign = 'center'
      for (const le of lineageEdges) {
        const sx = le.src.pos[0] + le.src.size[0] / 2
        const sy = le.src.pos[1] + le.src.size[1] / 2
        const dx = le.dst.pos[0] + le.dst.size[0] / 2
        const dy = le.dst.pos[1] + le.dst.size[1] / 2
        ctx.beginPath()
        ctx.moveTo(sx, sy)
        ctx.lineTo(dx, dy)
        ctx.stroke()
        // 箭头指向 dst：run --fulfills--> task 的方向要读得出来。
        const ang = Math.atan2(dy - sy, dx - sx)
        const ax = (sx + dx) / 2
        const ay = (sy + dy) / 2
        ctx.setLineDash([])
        ctx.beginPath()
        ctx.moveTo(ax, ay)
        ctx.lineTo(ax - 9 * Math.cos(ang - 0.42), ay - 9 * Math.sin(ang - 0.42))
        ctx.lineTo(ax - 9 * Math.cos(ang + 0.42), ay - 9 * Math.sin(ang + 0.42))
        ctx.closePath()
        ctx.fill()
        ctx.fillText(le.type, ax, ay - 8)
        ctx.setLineDash([7, 5])
      }
      ctx.restore()
    }
  }

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
    void agent.setScope(root)
  }

  function goBack() {
    if (navBack.length === 0) return
    navFwd = [...navFwd, currentRootId]
    currentRootId = navBack[navBack.length - 1]
    navBack = navBack.slice(0, -1)
    selectedId = null
    void load()
    void agent.setScope(currentRootId)
  }

  function goForward() {
    if (navFwd.length === 0) return
    navBack = [...navBack, currentRootId]
    currentRootId = navFwd[navFwd.length - 1]
    navFwd = navFwd.slice(0, -1)
    selectedId = null
    void load()
    void agent.setScope(currentRootId)
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
    void agent.initialize()
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
          scheduleReload()
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

  // A CLI burst (run bracket close: run + files + evidence + edges) emits one
  // commit per apply_patch; reloading per commit stacks fetch+rebuild work and
  // froze the canvas in rehearsal. Trailing debounce collapses a burst into
  // one reload of the final state.
  let reloadTimer: number | null = null
  function scheduleReload() {
    if (reloadTimer !== null) window.clearTimeout(reloadTimer)
    reloadTimer = window.setTimeout(() => {
      reloadTimer = null
      void load()
    }, 250)
  }

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
  // the flush loop forever.
  $: if (selectedNode !== undefined) queueMicrotask(resizeCanvas)
</script>

<header>
  <strong class="brand"><span class="brand-mark">✦</span>Simulanka</strong>
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
  <button
    on:click={() => (registryOpen = !registryOpen)}
    class:active-tool={registryOpen}
    aria-expanded={registryOpen}
    title="查看当前 Profile/Capability Registry"
  >
    Registry
  </button>
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
    {registryDescriptor}
    onOpenFile={(req) => (fileRequest = req)}
    onJumpTo={(id) => void jumpToEntity(id)}
    onResolveNote={(id) => void resolveEscalate(id)}
    onAttachNode={(node) =>
      agent.addPendingRef({ kind: 'node', ref_id: node.id }, `${node.type} · ${node.name}`)}
    onAttachPort={(port) =>
      agent.addPendingRef(
        { kind: 'port', ref_id: port.id },
        `port · ${selectedNode?.name ?? port.node_id}/${port.name}`,
      )}
  />
  {#if fileRequest}
    <FileViewer request={fileRequest} onClose={() => (fileRequest = null)} />
  {/if}
  {#if edgeMenu}
    <EdgeMenu
      x={edgeMenu.x}
      y={edgeMenu.y}
      edge={edgeMenu.edge}
      srcName={namesById.get(edgeMenu.edge.src) ?? edgeMenu.edge.src}
      dstName={namesById.get(edgeMenu.edge.dst) ?? edgeMenu.edge.dst}
      onClose={() => (edgeMenu = null)}
      onVerdict={(v) => void edgeVerdict(edgeMenu!.edge, v)}
      onAccept={() => void edgeAccept(edgeMenu!.edge)}
      onToggleDiscuss={() => void edgeToggleDiscuss(edgeMenu!.edge)}
      onAttach={() => {
        const activeEdge = edgeMenu!.edge
        agent.addPendingRef(
          { kind: 'edge', ref_id: activeEdge.id },
          `edge · ${namesById.get(activeEdge.src) ?? activeEdge.src} → ${namesById.get(activeEdge.dst) ?? activeEdge.dst}`,
        )
        edgeMenu = null
      }}
    />
  {/if}
  {#if menu}
    <ContextMenu
      x={menu.x}
      y={menu.y}
      mode={menu.mode}
      nodes={menu.nodes}
      affordances={menu.affordances}
      groups={templateGroups}
      onClose={() => (menu = null)}
      onPick={menuAddNode}
      onAction={menuAction}
      onDeleteTemplate={menuDeleteTemplate}
    />
  {/if}
  <AgentCompanion controller={agent} />
  {#if registryOpen}
    <RegistryPanel
      descriptor={registryDescriptor}
      onClose={() => (registryOpen = false)}
    />
  {/if}
</main>

<style>
  /* Workspace shell; component styles own the effective v2 appearance. */
  header {
    position: relative;
    display: flex;
    gap: 8px;
    align-items: center;
    min-height: 46px;
    box-sizing: border-box;
    padding: 7px 12px;
    background: #0a1624;
    border-bottom: 1px solid var(--hairline-2);
    font-size: 13px;
  }
  .brand {
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--ivory);
    display: flex;
    align-items: baseline;
    gap: 7px;
    user-select: none;
  }
  .brand-mark {
    font-size: 13px;
    color: var(--blue);
  }
  header button {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 3px;
    padding: 4px 12px;
    cursor: pointer;
    font-family: inherit;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  header button:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  header button.active-tool {
    border-color: var(--gold);
    color: var(--gold-bright);
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
    height: calc(100vh - 46px);
    /* FileViewer 抽屉以此为定位容器（position: absolute; right: 0） */
    position: relative;
  }
  canvas {
    display: block;
    flex: 1;
    min-width: 0;
    height: 100%;
    background: var(--canvas-bg);
  }
</style>
