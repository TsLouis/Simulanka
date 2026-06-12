<script lang="ts">
  // §13.6 verify-discuss panel, Claude-side cut: ghost review (accept /
  // reject-with-reason) + the live disagreement set. The discussion chat
  // itself arrives with the opencode-session harness (Codex seam) — until
  // then resolving a disagreement means deleting or re-accepting the edge
  // on canvas / via the buttons here.
  import type { DisagreementDTO, EdgeDTO, PortDTO } from './types'
  import { isPendingGhost } from './verify'

  export let edges: EdgeDTO[] // current view: edges + boundary_edges
  export let disagreements: DisagreementDTO[]
  export let namesById: Map<string, string>
  export let portsById: Map<string, PortDTO>
  export let selectedId: string | null // selected node filters the ghost list
  export let onAccept: (edgeId: string) => void
  export let onReject: (edgeId: string, note: string) => void
  export let onDiscuss: (edgeId: string, discuss: boolean) => void

  $: ghosts = edges.filter(isPendingGhost)
  // 选中 port 浮 ghost (node granularity): with a node selected, only its
  // ghosts show, grouped per port below.
  $: shownGhosts = selectedId
    ? ghosts.filter(e => e.src === selectedId || e.dst === selectedId)
    : ghosts

  // Reject form state: which ghost has its reason form open, and the draft.
  let rejecting: string | null = null
  let draft = ''

  function startReject(edgeId: string) {
    rejecting = edgeId
    draft = ''
  }

  function submitReject() {
    if (!rejecting || !draft.trim()) return
    onReject(rejecting, draft.trim())
    rejecting = null
    draft = ''
  }

  const name = (id: string): string => namesById.get(id) ?? id
  const portName = (id: string | null): string => {
    if (!id) return '?'
    const p = portsById.get(id)
    if (!p) return '?'
    return typeof p.attrs.label === 'string' ? p.attrs.label : p.name
  }

  const REASON_LABELS: Record<string, string> = {
    user_rejected_ghost: '人拒提议',
    agent_flagged_user_edge: 'agent 质疑',
    disputed: '裁决冲突',
    manual: '手动拉入',
  }

  const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)
</script>

<aside class="verify">
  <section>
    <h3>
      Ghost 提议
      {#if selectedId}<span class="filter">@ {name(selectedId)}</span>{/if}
      <span class="count">{shownGhosts.length}</span>
    </h3>
    {#if shownGhosts.length === 0}
      <p class="muted">
        {selectedId ? '选中节点上无待核 ghost' : '当前视图无待核 ghost'}
      </p>
    {:else}
      <ul>
        {#each shownGhosts as e (e.id)}
          <li class="ghost">
            <div class="endpoints">
              <span class="ep">{name(e.src)}<em>.{portName(e.src_port)}</em></span>
              <span class="arrow">→</span>
              <span class="ep">{name(e.dst)}<em>.{portName(e.dst_port)}</em></span>
              {#if str(e.attrs.output_slice)}
                <code class="slice">{e.attrs.output_slice}</code>
              {/if}
            </div>
            {#if str(e.attrs.citation)}
              <code class="citation">{e.attrs.citation}</code>
            {/if}
            {#if rejecting === e.id}
              <div class="reject-form">
                <!-- svelte-ignore a11y_autofocus — the form opens on explicit click -->
                <textarea
                  bind:value={draft}
                  rows="2"
                  autofocus
                  placeholder="必填：我认为…因为…（这是给 agent 的可反驳靶子）"
                ></textarea>
                <div class="row">
                  <button class="danger" disabled={!draft.trim()} on:click={submitReject}>
                    提交拒绝
                  </button>
                  <button on:click={() => (rejecting = null)}>取消</button>
                </div>
              </div>
            {:else}
              <div class="row">
                <button class="ok" on:click={() => onAccept(e.id)}>✓ 接受</button>
                <button class="danger" on:click={() => startReject(e.id)}>✗ 拒绝</button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section>
    <h3>分歧集 <span class="count">{disagreements.length}</span></h3>
    {#if disagreements.length === 0}
      <p class="muted">无分歧 — 拒绝 ghost、agent 质疑或手动拉入的边会进入这里</p>
    {:else}
      <ul>
        {#each disagreements as d (d.id)}
          <li class="dis">
            <div class="endpoints">
              <span class="ep">{name(d.src)}</span>
              <span class="arrow">→</span>
              <span class="ep">{name(d.dst)}</span>
              {#each d.reasons as r}
                <span class="reason reason-{r}">{REASON_LABELS[r] ?? r}</span>
              {/each}
            </div>
            {#if str(d.attrs.verdict)}
              <div class="verdict-line">
                verdict: <b>{d.attrs.verdict}</b>
                {#if str(d.attrs.verdict_by)}<span class="by">by {d.attrs.verdict_by}</span>{/if}
              </div>
            {/if}
            {#if str(d.attrs.verdict_note)}
              <blockquote>{d.attrs.verdict_note}</blockquote>
            {/if}
            {#if d.reasons.includes('manual')}
              <div class="row">
                <button on:click={() => onDiscuss(d.id, false)}>移出讨论</button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
    <p class="seam">讨论会话（opencode 续聊 harness）接入后，分歧将在此逐条对谈落边。</p>
  </section>
</aside>

<style>
  .verify {
    width: 340px;
    background: #1f1f1f;
    border-left: 1px solid #333;
    color: #ddd;
    font-size: 12px;
    overflow-y: auto;
    padding: 12px 14px 24px;
    box-sizing: border-box;
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
  section {
    margin-bottom: 18px;
  }
  .filter {
    color: #e0a23a;
    text-transform: none;
  }
  .count {
    margin-left: auto;
    background: #333;
    border-radius: 8px;
    padding: 0 7px;
    color: #ccc;
  }
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  li {
    border: 1px solid #2e2e2e;
    border-radius: 4px;
    padding: 8px;
    margin-bottom: 8px;
    background: #232323;
  }
  li.dis {
    border-left: 3px solid #d16a5a;
  }
  .endpoints {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
  }
  .ep {
    color: #fff;
  }
  .ep em {
    color: #9ab;
    font-style: normal;
    font-family: ui-monospace, monospace;
    font-size: 11px;
  }
  .arrow {
    color: #777;
  }
  .slice {
    font-family: ui-monospace, monospace;
    font-size: 10px;
    color: #cde;
    background: #243044;
    border-radius: 2px;
    padding: 1px 5px;
  }
  .citation {
    display: block;
    margin-top: 6px;
    background: #181818;
    border: 1px solid #2a2a2a;
    border-radius: 3px;
    padding: 4px 6px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: #b8c4d0;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .row {
    display: flex;
    gap: 6px;
    margin-top: 8px;
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
  button.ok {
    border-color: #3a6;
    color: #8fe08f;
  }
  button.danger {
    border-color: #a55;
    color: #f0aeae;
  }
  .reject-form {
    margin-top: 8px;
  }
  textarea {
    width: 100%;
    box-sizing: border-box;
    background: #111;
    color: #ddd;
    border: 1px solid #444;
    padding: 4px 6px;
    font-family: inherit;
    font-size: 12px;
    resize: vertical;
  }
  .reason {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-radius: 2px;
    padding: 1px 5px;
    background: #3a2a1f;
    color: #e0b88f;
  }
  .reason-disputed {
    background: #3a1f1f;
    color: #e08f8f;
  }
  .reason-manual {
    background: #1f2a3a;
    color: #8fb8e0;
  }
  .verdict-line {
    margin-top: 6px;
    color: #aaa;
  }
  .by {
    color: #777;
    margin-left: 4px;
  }
  blockquote {
    margin: 6px 0 0;
    padding: 4px 8px;
    border-left: 2px solid #555;
    color: #ccc;
    background: #1b1b1b;
  }
  .muted {
    color: #888;
    margin: 4px 0;
  }
  .seam {
    color: #666;
    font-size: 11px;
    border-top: 1px dashed #333;
    padding-top: 8px;
    margin-top: 4px;
  }
</style>
