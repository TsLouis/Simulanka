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
  .discuss {
    border-top: 1px dashed #333;
    padding-top: 10px;
  }
  h3 {
    margin: 0 0 6px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .unit {
    text-transform: none;
    color: #666;
  }
  .muted {
    color: #888;
    margin: 4px 0 8px;
  }
  .start-row {
    display: flex;
    gap: 6px;
  }
  input {
    flex: 1;
    min-width: 0;
    background: #111;
    color: #ddd;
    border: 1px solid #444;
    padding: 4px 6px;
    font-family: inherit;
    font-size: 12px;
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
    border-radius: 6px;
    padding: 6px 8px;
    max-width: 92%;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg.user {
    align-self: flex-end;
    background: #2c3e50;
    color: #dde8f5;
  }
  .msg.agent {
    align-self: flex-start;
    background: #262626;
    border: 1px solid #2e2e2e;
  }
  .msg.pending {
    color: #777;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 6px;
  }
  .chip {
    font-family: ui-monospace, monospace;
    font-size: 10px;
    border-radius: 3px;
    padding: 1px 6px;
    cursor: default;
  }
  .chip.ok {
    background: #1d3324;
    color: #8fe08f;
    border: 1px solid #3a6;
  }
  .chip.no {
    background: #331f1f;
    color: #f0aeae;
    border: 1px solid #a55;
  }
  .composer {
    display: flex;
    gap: 6px;
    align-items: flex-end;
  }
  textarea {
    flex: 1;
    box-sizing: border-box;
    background: #111;
    color: #ddd;
    border: 1px solid #444;
    padding: 4px 6px;
    font-family: inherit;
    font-size: 12px;
    resize: vertical;
  }
  button {
    background: #333;
    color: #ddd;
    border: 1px solid #555;
    padding: 3px 10px;
    cursor: pointer;
    font-size: 12px;
  }
  button:hover {
    background: #444;
  }
  button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  button.primary {
    border-color: #5a7fd1;
    color: #b9ccf2;
  }
</style>
