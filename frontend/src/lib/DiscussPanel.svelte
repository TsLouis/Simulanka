<script lang="ts" context="module">
  import type { DiscussionOpResult } from './api'

  export interface ChatMsg {
    role: 'user' | 'agent'
    text: string
    applied?: DiscussionOpResult[]
    rejected?: DiscussionOpResult[]
  }
</script>

<script lang="ts">
  // §13.6 discussion chat: one batch, one opencode session. State lives in
  // App.svelte (panel toggling must not lose the thread); this component is
  // presentation + callbacks, like VerifyPanel. Applied/rejected op chips on
  // each agent turn make the write-matrix gate visible — the human sees what
  // the agent changed and what the server refused, in place.
  export let messages: ChatMsg[]
  export let active: boolean
  export let busy: boolean
  export let disagreementCount: number
  export let onStart: (model: string | null) => void
  export let onSend: (text: string) => void

  let draft = ''
  let model = ''
  let thread: HTMLDivElement | null = null

  function send() {
    const text = draft.trim()
    if (!text || busy) return
    draft = ''
    onSend(text)
  }

  function onKeydown(ev: KeyboardEvent) {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault()
      send()
    }
  }

  // Keep the newest turn in view as the thread grows.
  $: if (messages.length && thread) {
    thread.scrollTop = thread.scrollHeight
  }

  const opLabel = (r: DiscussionOpResult): string => {
    const kind = typeof r.op.op === 'string' ? r.op.op : '?'
    const edge = r.edge_id ?? (typeof r.op.edge_id === 'string' ? r.op.edge_id : '')
    return edge ? `${kind} ${edge.slice(0, 12)}…` : kind
  }
</script>

<section class="discuss">
  <h3>讨论 <span class="unit">一批一场</span></h3>

  {#if !active}
    <p class="muted">
      {disagreementCount > 0
        ? `${disagreementCount} 条分歧将整批进入同一会话 — 一个架构性误解常同时解释多条。`
        : '无分歧可讨论 — 先在上方核对 ghost 或拉边入讨论。'}
    </p>
    <div class="start-row">
      <input
        bind:value={model}
        placeholder="模型（留空用 opencode 默认）"
        disabled={busy}
      />
      <button
        class="primary"
        disabled={busy || disagreementCount === 0}
        on:click={() => onStart(model.trim() || null)}
      >
        {busy ? '开场中…' : '开始讨论'}
      </button>
    </div>
  {:else}
    <div class="thread" bind:this={thread}>
      {#each messages as m}
        <div class="msg {m.role}">
          <div class="text">{m.text}</div>
          {#if m.applied?.length || m.rejected?.length}
            <div class="chips">
              {#each m.applied ?? [] as r}
                <span class="chip ok" title={JSON.stringify(r.op)}>✓ {opLabel(r)}</span>
              {/each}
              {#each m.rejected ?? [] as r}
                <span class="chip no" title={r.reason}>✗ {opLabel(r)}</span>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
      {#if busy}
        <div class="msg agent pending">…</div>
      {/if}
    </div>
    <div class="composer">
      <textarea
        bind:value={draft}
        rows="2"
        placeholder="反驳或追问 — Enter 发送，Shift+Enter 换行"
        disabled={busy}
        on:keydown={onKeydown}
      ></textarea>
      <button class="primary" disabled={busy || !draft.trim()} on:click={send}>发送</button>
    </div>
  {/if}
</section>

<style>
  /* 星图册 · 讨论席 —— 与核对面板同窗，金线隔断（调色板见 app.css :root） */
  .discuss {
    border-top: 1px dashed var(--gold-dim);
    padding-top: 12px;
  }
  h3 {
    margin: 0 0 8px;
    font-family: var(--font-display);
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 0.12em;
    color: var(--gold);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  h3::before {
    content: '✦';
    font-size: 9px;
    color: var(--gold-dim);
  }
  .unit {
    font-family: var(--font-body);
    font-size: 10px;
    letter-spacing: 0;
    color: var(--muted);
  }
  .muted {
    color: var(--muted);
    margin: 4px 0 8px;
  }
  .start-row {
    display: flex;
    gap: 6px;
  }
  input {
    flex: 1;
    min-width: 0;
    background: var(--panel-3);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 4px;
    padding: 4px 7px;
    font-family: inherit;
    font-size: 12px;
  }
  input:focus {
    outline: none;
    border-color: var(--gold-dim);
  }
  .thread {
    max-height: 320px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 8px;
  }
  .msg {
    border-radius: 8px;
    padding: 7px 9px;
    max-width: 92%;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg.user {
    align-self: flex-end;
    background: #33405e;
    color: #e6edf8;
    border: 1px solid #45557d;
    border-radius: 8px 8px 2px 8px;
  }
  .msg.agent {
    align-self: flex-start;
    background: var(--panel-2);
    border: 1px solid var(--hairline-2);
    border-radius: 8px 8px 8px 2px;
  }
  .msg.pending {
    color: var(--muted);
    animation: pending-pulse 1.4s ease-in-out infinite;
  }
  @keyframes pending-pulse {
    0%,
    100% {
      opacity: 0.5;
    }
    50% {
      opacity: 1;
    }
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 6px;
  }
  .chip {
    font-family: var(--font-mono);
    font-size: 10px;
    border-radius: 3px;
    padding: 1px 6px;
    cursor: default;
  }
  .chip.ok {
    background: var(--jade-deep);
    color: var(--jade);
    border: 1px solid #3d6b52;
  }
  .chip.no {
    background: var(--crimson-deep);
    color: var(--crimson);
    border: 1px solid #7a4038;
  }
  .composer {
    display: flex;
    gap: 6px;
    align-items: flex-end;
  }
  textarea {
    flex: 1;
    box-sizing: border-box;
    background: var(--panel-3);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 4px;
    padding: 5px 7px;
    font-family: inherit;
    font-size: 12px;
    resize: vertical;
  }
  textarea:focus {
    outline: none;
    border-color: var(--gold-dim);
    box-shadow: 0 0 0 2px rgba(217, 186, 125, 0.12);
  }
  button {
    background: var(--panel-3);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 4px;
    padding: 4px 11px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    transition:
      border-color 0.15s,
      color 0.15s,
      box-shadow 0.15s;
  }
  button:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  /* 主 CTA：鎏金按钮 —— 开始讨论 / 发送 */
  button.primary {
    background: linear-gradient(180deg, #d9ba7d 0%, #b99a5e 100%);
    border-color: var(--gold);
    color: #241c0c;
    font-weight: 500;
  }
  button.primary:hover:not(:disabled) {
    box-shadow: 0 0 12px var(--gold-glow);
    color: #241c0c;
  }
</style>
