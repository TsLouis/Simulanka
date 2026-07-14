<script lang="ts" context="module">
  import type { DiscussionOpResult } from './api'

  // One chat entry. Applied/rejected are the agent's op-block results — the
  // write-matrix gate's outcome rides with the message that caused it.
  export interface ChatMsg {
    role: 'user' | 'agent'
    text: string
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
  export let onClose: () => void = () => {}

  // Drag by header. position is component-local; default parks at the right
  // edge above the dock.
  let x = window.innerWidth - 400
  let y = 64
  let dragging: { dx: number; dy: number } | null = null
  function dragStart(e: MouseEvent) {
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

<section class="chat-node" style="left: {x}px; top: {y}px;">
  <header role="toolbar" tabindex="-1" on:mousedown|preventDefault={dragStart}>
    <span class="dot" class:on={active} title={active ? '会话进行中' : '未开会话'}></span>
    <strong>会话</strong>
    <button class="close" on:click={onClose} title="收起">✕</button>
  </header>

  <div class="scroll" bind:this={scrollEl}>
    {#each messages as m, i (i)}
      <div class="msg {m.role}">
        <div class="bubble">{m.text}</div>
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
  .close {
    margin-left: auto;
    background: transparent;
    border: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 12px;
  }
  .close:hover {
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
