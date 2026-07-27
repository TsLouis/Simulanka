<script lang="ts" context="module">
  import type { DiscussionOpResult } from './api'

  // One chat entry. Applied/rejected are the agent's op-block results — the
  // write-matrix gate's outcome rides with the message that caused it.
  export interface ChatMsg {
    role: 'user' | 'agent' | 'system'
    text: string
    kind?: 'message' | 'tool_call' | 'tool_result' | 'status' | 'error'
    status?: string
    toolName?: string
    callId?: string
    input?: unknown
    output?: unknown
    applied?: DiscussionOpResult[]
    rejected?: DiscussionOpResult[]
  }
</script>

<script lang="ts">
  import { afterUpdate } from 'svelte'

  // 会话节点：画布上的浮动消息面（node 观感、可拖动）。这是框架原语——
  // 只做消息的展示；将来的消息类型（分歧、escalate、快检……）作为内容长在
  // 这个面里，不另立面板（feedback: no-single-purpose-buttons）。消息本体
  // 在会话文件里（图皮文件芯），这里只是皮。
  export let messages: ChatMsg[] = []
  export let active = false
  export let busy = false
  export let title = '会话'
  export let subtitle: string | null = null
  export let onClose: () => void = () => {}
  let fullscreen = false

  // Drag by header. position is component-local; default parks at the right
  // edge above the dock.
  let x = window.innerWidth - 400
  let y = 64
  let dragging: { dx: number; dy: number } | null = null
  function dragStart(e: MouseEvent) {
    if (fullscreen) return
    dragging = { dx: e.clientX - x, dy: e.clientY - y }
  }
  function dragMove(e: MouseEvent) {
    if (!dragging) return
    x = Math.max(0, Math.min(e.clientX - dragging.dx, window.innerWidth - 120))
    y = Math.max(44, Math.min(e.clientY - dragging.dy, window.innerHeight - 80))
  }
  function dragEnd() {
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

<section class="chat-node" class:fullscreen style="left: {x}px; top: {y}px;">
  <header role="toolbar" tabindex="-1" on:mousedown|preventDefault={dragStart}>
    <span class="dot" class:on={active} title={active ? '会话进行中' : '未开会话'}></span>
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
      on:click={onClose}
      title="收起"
    >✕</button>
  </header>

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
        {#if m.applied && m.applied.length > 0}
          <div class="ops ok">✓ 落图 {m.applied.length} 项</div>
        {/if}
        {#if m.rejected && m.rejected.length > 0}
          <div class="ops bad">⚠ 写权闸拒绝 {m.rejected.length} 项</div>
        {/if}
      </div>
    {/each}
    {#if busy}
      <div class="msg agent"><div class="bubble thinking">正在思考…</div></div>
    {/if}
    {#if messages.length === 0 && !busy}
      <div class="empty">还没有消息。底部输入条发一句,会话会锚定当前选择。</div>
    {/if}
  </div>
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
  .thinking {
    color: var(--muted);
    letter-spacing: 2px;
  }
  .ops {
    font-size: 11px;
    margin-top: 2px;
  }
  .ops.ok {
    color: var(--jade);
  }
  .ops.bad {
    color: var(--crimson);
  }
  .empty {
    color: var(--muted);
    text-align: center;
    padding: 18px 8px;
  }
</style>
