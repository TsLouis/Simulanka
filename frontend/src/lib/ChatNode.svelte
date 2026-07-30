<script lang="ts" context="module">
  // One provider-neutral chat entry projected from the normalized event stream.
  export interface ChatMsg {
    role: 'user' | 'agent' | 'system'
    text: string
    kind?: 'message' | 'tool_call' | 'tool_result' | 'status' | 'error'
    status?: string
    toolName?: string
    callId?: string
    input?: unknown
    output?: unknown
    details?: Record<string, unknown>
  }
</script>

<script lang="ts">
  import { afterUpdate } from 'svelte'
  import type { SessionDTO } from './api'

  // 会话节点：画布上的浮动消息面（node 观感、可拖动）。这是框架原语——
  // 只做消息的展示；将来的消息类型（分歧、escalate、快检……）作为内容长在
  // 这个面里，不另立面板（feedback: no-single-purpose-buttons）。消息本体
  // 在会话文件里（图皮文件芯），这里只是皮。
  export let messages: ChatMsg[] = []
  export let nodeId = 'chat:draft'
  export let active = false
  export let selected = false
  export let draft = false
  export let busy = false
  export let title = '会话'
  export let subtitle: string | null = null
  export let sessionId: string | null = null
  export let sessions: SessionDTO[] = []
  export let loading = false
  export let actionBusy = false
  export let error: string | null = null
  export let cacheLabel: string | null = null
  export let onSelectSession: (sessionId: string) => void = () => {}
  export let onNewSession: () => void = () => {}
  export let onRefreshSessions: () => void = () => {}
  export let onForkSession: () => void = () => {}
  export let onArchiveSession: () => void = () => {}
  export let onActivate: () => void = () => {}
  export let onMove: (x: number, y: number) => void = () => {}
  export let onClose: () => void = () => {}
  let fullscreen = false
  let collapsed = false
  let sessionsOpen = false
  $: activeSession =
    sessions.find(session => session.session_id === sessionId) ?? null

  // Position belongs to the graph-view UI sidecar bucket, keyed by
  // ``chat:<tree_id>``. The parent persists a completed drag.
  export let x = window.innerWidth - 400
  export let y = 64
  let dragging: { dx: number; dy: number } | null = null
  function dragStart(e: MouseEvent) {
    if (fullscreen) return
    onActivate()
    dragging = { dx: e.clientX - x, dy: e.clientY - y }
  }
  function dragMove(e: MouseEvent) {
    if (!dragging) return
    x = Math.max(0, Math.min(e.clientX - dragging.dx, window.innerWidth - 120))
    y = Math.max(44, Math.min(e.clientY - dragging.dy, window.innerHeight - 80))
  }
  function dragEnd() {
    if (dragging) onMove(Math.round(x), Math.round(y))
    dragging = null
  }

  function formatDetail(value: unknown): string {
    if (typeof value === 'string') return value
    if (value === undefined) return '(无)'
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }

  function shortSessionId(value: string): string {
    return value.length > 12 ? `…${value.slice(-10)}` : value
  }

  function detailSummary(details: Record<string, unknown>): string {
    const usage = details.usage
    if (usage && typeof usage === 'object' && !Array.isArray(usage)) {
      const cached = (usage as Record<string, unknown>).cached_input_tokens
      return `usage · cache ${typeof cached === 'number' ? cached : '未报告'}`
    }
    const bundles = details.context_bundles
    if (Array.isArray(bundles)) return `context · ${bundles.length} bundle`
    return '事件详情'
  }

  // Follow the tail as messages stream in — but never via tick() inside a
  // reactive statement: Svelte 5's tick() is microtask + flushSync, and from
  // a legacy `$:` that re-enters the flush forever. Mounting this component
  // froze the entire page (彩排实测 2026-07-14). afterUpdate runs once per
  // completed render, outside the flush loop.
  let scrollEl: HTMLDivElement | null = null
  let renderedBubbles = -1
  afterUpdate(() => {
    const count = messages.length + (busy ? 1 : 0)
    if (scrollEl && count !== renderedBubbles) {
      renderedBubbles = count
      scrollEl.scrollTop = scrollEl.scrollHeight
    }
  })
</script>

<svelte:window on:mousemove={dragMove} on:mouseup={dragEnd} />

<section
  class="chat-node"
  class:fullscreen
  class:collapsed
  class:selected
  data-chat-node={nodeId}
  style="left: {x}px; top: {y}px;"
>
  <header role="toolbar" tabindex="-1" on:mousedown|preventDefault={dragStart}>
    <span class="dot" class:on={active} title={active ? '已绑定持久化会话' : '新会话草稿'}></span>
    <span class="heading">
      <strong>{title}</strong>
      {#if subtitle}<small title={subtitle}>{subtitle}</small>{/if}
    </span>
    <button
      class="icon-btn expand"
      on:mousedown|stopPropagation
      on:click={() => (fullscreen = !fullscreen)}
      title={fullscreen ? '退出全屏' : '全屏'}
    >{fullscreen ? '↙' : '⛶'}</button>
    <button
      class="icon-btn close"
      on:mousedown|stopPropagation
      on:click={() => {
        if (draft) onClose()
        else collapsed = !collapsed
      }}
      title={draft ? '关闭新会话草稿' : collapsed ? '展开会话节点' : '折叠会话节点'}
    >{draft ? '✕' : collapsed ? '□' : '—'}</button>
  </header>

  {#if !collapsed}
    <div class="session-strip">
      <button
        class:open={sessionsOpen}
        on:click={() => (sessionsOpen = !sessionsOpen)}
        title="查看和切换本节点内的会话分支"
      >⑂ {sessions.length}</button>
      {#if sessionId}
        <code class="session-id" title={sessionId}>{shortSessionId(sessionId)}</code>
      {:else}
        <span class="new-label">新会话树草稿</span>
      {/if}
      {#if cacheLabel}<span class="cache-label">{cacheLabel}</span>{/if}
      <span class="session-spacer"></span>
      <button on:click={onRefreshSessions} disabled={loading} title="刷新当前层会话树">↻</button>
      <button on:click={onForkSession} disabled={!sessionId || busy || actionBusy} title="在本节点内从当前分支 fork">fork</button>
      <button
        on:click={onArchiveSession}
        disabled={!sessionId || busy || actionBusy || activeSession?.status === 'archived' || activeSession?.status === 'running'}
        title="非破坏归档当前分支"
      >归档</button>
      <button on:click={onNewSession} disabled={busy || actionBusy} title="在当前层创建另一棵会话树">＋树</button>
    </div>

    {#if sessionsOpen}
      <div class="session-list" aria-label="当前 ChatNode 的会话分支">
        {#if sessions.length === 0}
          <span class="session-empty">{loading ? '正在加载…' : '还没有持久化分支'}</span>
        {:else}
          {#each sessions as session (session.session_id)}
            <button
              class:selected={session.session_id === sessionId}
              class:archived={session.status === 'archived'}
              disabled={busy || actionBusy}
              title={session.session_id}
              on:click={() => {
                onSelectSession(session.session_id)
                sessionsOpen = false
              }}
            >
              <code>{shortSessionId(session.session_id)}</code>
              <span>{session.parent_session_id ? 'fork' : 'root'}</span>
              <i>{session.status}</i>
            </button>
          {/each}
        {/if}
      </div>
    {/if}

    {#if error}
      <div class="session-error" role="alert">{error}</div>
    {/if}

    <div class="scroll" bind:this={scrollEl}>
      {#each messages as m, i (i)}
        <div class="msg {m.role}">
          {#if m.kind === 'tool_call' || m.kind === 'tool_result'}
            <details class="tool-card">
              <summary>
                <span class="tool-icon">{m.kind === 'tool_call' ? '⚙' : '✓'}</span>
                <strong>{m.toolName ?? 'tool'}</strong>
                <span class="tool-status">{m.status ?? (m.kind === 'tool_call' ? 'running' : 'done')}</span>
              </summary>
              {#if m.callId}<code class="call-id">{m.callId}</code>{/if}
              {#if m.kind === 'tool_call'}
                <span class="detail-label">输入</span>
                <pre>{formatDetail(m.input)}</pre>
              {:else}
                <span class="detail-label">结果</span>
                <pre>{formatDetail(m.output)}</pre>
              {/if}
            </details>
          {:else if m.kind === 'status'}
            <div class="status-line status-{m.status ?? 'event'}">{m.text}</div>
          {:else}
            <div class="bubble" class:error={m.kind === 'error'}>{m.text}</div>
          {/if}
          {#if m.details && Object.keys(m.details).length > 0}
            <details class="event-details">
              <summary>{detailSummary(m.details)}</summary>
              <pre>{formatDetail(m.details)}</pre>
            </details>
          {/if}
        </div>
      {/each}
      {#if busy}
        <div class="msg agent"><div class="bubble thinking">正在思考…</div></div>
      {/if}
      {#if messages.length === 0 && !busy}
        <div class="empty">还没有消息。直接在底部输入；所在层级不会自动加入上下文。</div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .chat-node {
    position: fixed;
    z-index: 30;
    width: 360px;
    max-height: 60vh;
    display: flex;
    flex-direction: column;
    background: linear-gradient(180deg, #1a2642 0%, #121b31 100%);
    border: 1px solid var(--hairline);
    border-radius: 10px;
    box-shadow:
      0 8px 28px rgba(0, 0, 0, 0.55),
      0 0 0 1px rgba(217, 186, 125, 0.08);
    font-size: 13px;
  }
  .chat-node.fullscreen {
    inset: 44px 18px 18px 18px !important;
    width: auto;
    max-height: none;
    z-index: 60;
  }
  .chat-node.selected {
    z-index: 35;
    border-color: var(--gold);
    box-shadow:
      0 10px 34px rgba(0, 0, 0, 0.62),
      0 0 0 2px rgba(217, 186, 125, 0.16);
  }
  .chat-node.collapsed {
    width: 250px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--hairline);
    cursor: grab;
    user-select: none;
    color: var(--gold-bright);
  }
  header:active {
    cursor: grabbing;
  }
  .heading {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .heading small {
    max-width: 230px;
    overflow: hidden;
    color: var(--muted);
    font-size: 10px;
    font-weight: normal;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3a4763;
  }
  .dot.on {
    background: var(--jade);
    box-shadow: 0 0 6px rgba(126, 207, 165, 0.8);
  }
  .icon-btn {
    background: transparent;
    border: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 12px;
  }
  .expand {
    margin-left: auto;
  }
  .icon-btn:hover {
    color: var(--ivory);
  }
  .scroll {
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .session-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 5px;
    min-height: 30px;
    padding: 4px 8px;
    border-bottom: 1px solid var(--hairline-2);
    background: rgba(9, 17, 31, 0.35);
  }
  .session-strip button {
    border: 1px solid var(--hairline);
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    cursor: pointer;
    font: inherit;
    font-size: 10px;
    padding: 3px 6px;
  }
  .session-strip button:hover:not(:disabled),
  .session-strip button.open {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  .session-strip button:disabled {
    cursor: default;
    opacity: 0.45;
  }
  .session-id,
  .new-label,
  .cache-label {
    color: var(--muted);
    font-size: 9px;
    white-space: nowrap;
  }
  .cache-label {
    color: var(--gold-dim);
  }
  .session-spacer {
    flex: 1;
  }
  .session-list {
    max-height: 180px;
    overflow-y: auto;
    padding: 5px;
    border-bottom: 1px solid var(--hairline);
    background: #0d1629;
  }
  .session-list > button {
    width: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 7px;
    margin-bottom: 3px;
    padding: 5px 7px;
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }
  .session-list > button:hover,
  .session-list > button.selected {
    border-color: var(--gold-dim);
    background: rgba(217, 186, 125, 0.08);
  }
  .session-list > button.archived {
    opacity: 0.62;
  }
  .session-list code {
    overflow: hidden;
    color: var(--gold-bright);
    text-overflow: ellipsis;
  }
  .session-list i {
    color: var(--muted);
    font-size: 9px;
    font-style: normal;
  }
  .session-empty,
  .session-error {
    display: block;
    padding: 7px;
    color: var(--muted);
    font-size: 10px;
  }
  .session-error {
    border-bottom: 1px solid rgba(232, 106, 106, 0.25);
    color: #f6b0b0;
  }
  .msg {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }
  .msg.user {
    align-items: flex-end;
  }
  .msg.system {
    align-items: stretch;
  }
  .bubble {
    max-width: 85%;
    padding: 6px 10px;
    border-radius: 9px;
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--panel-2);
    color: var(--text);
  }
  .msg.user .bubble {
    background: rgba(217, 186, 125, 0.14);
    border: 1px solid rgba(217, 186, 125, 0.3);
    color: var(--ivory);
  }
  .bubble.error {
    border: 1px solid rgba(232, 106, 106, 0.45);
    color: #f6b0b0;
  }
  .status-line {
    align-self: center;
    padding: 3px 8px;
    color: var(--muted);
    font-size: 11px;
  }
  .status-line.status-done {
    color: var(--jade);
  }
  .status-line.status-failed {
    color: var(--crimson);
  }
  .tool-card {
    width: min(100%, 520px);
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: rgba(9, 17, 31, 0.72);
  }
  .tool-card summary {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 7px 9px;
    cursor: pointer;
    color: var(--text);
  }
  .tool-icon {
    color: var(--gold);
  }
  .tool-status {
    margin-left: auto;
    color: var(--muted);
    font-size: 10px;
    text-transform: uppercase;
  }
  .detail-label,
  .call-id {
    display: block;
    margin: 6px 9px 2px;
    color: var(--gold-dim);
    font-size: 10px;
  }
  .tool-card pre {
    max-height: 240px;
    margin: 4px 9px 9px;
    overflow: auto;
    padding: 7px;
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    font-size: 11px;
    white-space: pre-wrap;
  }
  .event-details {
    max-width: 85%;
    margin-top: 3px;
    color: var(--muted);
    font-size: 10px;
  }
  .event-details summary {
    cursor: pointer;
    color: var(--gold-dim);
  }
  .event-details pre {
    max-height: 180px;
    overflow: auto;
    margin: 3px 0 0;
    padding: 6px;
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    white-space: pre-wrap;
  }
  .thinking {
    color: var(--muted);
    letter-spacing: 2px;
  }
  .empty {
    color: var(--muted);
    text-align: center;
    padding: 18px 8px;
  }
</style>
