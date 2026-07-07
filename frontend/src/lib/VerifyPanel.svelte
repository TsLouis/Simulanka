<script lang="ts">
  // §13.6 verify-discuss panel: ghost review (accept / reject-with-reason),
  // the live disagreement set, and — via the slot — the discussion chat
  // (DiscussPanel, driven by App.svelte state).
  import type { DisagreementDTO, EdgeDTO, PortDTO } from './types'
  import { isPendingGhost } from './verify'

  export let edges: EdgeDTO[] // current view: edges + boundary_edges
  export let disagreements: DisagreementDTO[]
  export let namesById: Map<string, string>
  export let portsById: Map<string, PortDTO>
  export let selectedId: string | null // selected node filters the ghost list
  // Edges with an action in flight: their buttons lock until the request
  // settles, so the SSE roundtrip gap can't read as "click did nothing".
  export let busyEdges: Set<string> = new Set()
  export let onAccept: (edgeId: string) => void
  export let onReject: (edgeId: string, note: string) => void
  export let onDiscuss: (edgeId: string, discuss: boolean) => void

  $: ghosts = edges.filter(isPendingGhost)
  // 选中 port 浮 ghost (node granularity): with a node selected, only its
  // ghosts show, grouped per port below.
  $: shownGhosts = selectedId
    ? ghosts.filter(e => e.src === selectedId || e.dst === selectedId)
    : ghosts

  // §13.6 手动拉入: any real (non-ghost) edge can be pulled into the
  // discussion set by hand. Selection-scoped on purpose — drill-down views
  // carry hundreds of trace edges; an unscoped list would swamp the panel.
  $: pullable = selectedId
    ? edges.filter(
        e =>
          e.type === 'data_flow' && // view payload mixes in `contains` — server refuses those
          !isPendingGhost(e) &&
          e.attrs.discuss !== true &&
          (e.src === selectedId || e.dst === selectedId),
      )
    : []

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
                  <button
                    class="danger"
                    disabled={!draft.trim() || busyEdges.has(e.id)}
                    on:click={submitReject}
                  >
                    提交拒绝
                  </button>
                  <button on:click={() => (rejecting = null)}>取消</button>
                </div>
              </div>
            {:else}
              <div class="row">
                <button class="ok" disabled={busyEdges.has(e.id)} on:click={() => onAccept(e.id)}>
                  ✓ 接受
                </button>
                <button class="danger" disabled={busyEdges.has(e.id)} on:click={() => startReject(e.id)}>
                  ✗ 拒绝
                </button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section>
    <h3>
      拉入讨论
      {#if selectedId}<span class="filter">@ {name(selectedId)}</span>{/if}
      <span class="count">{pullable.length}</span>
    </h3>
    {#if !selectedId}
      <p class="muted">选中节点后，其实边可手动拉入讨论</p>
    {:else if pullable.length === 0}
      <p class="muted">选中节点上无可拉入的边</p>
    {:else}
      <ul>
        {#each pullable as e (e.id)}
          <li>
            <div class="endpoints">
              <span class="ep">{name(e.src)}<em>.{portName(e.src_port)}</em></span>
              <span class="arrow">→</span>
              <span class="ep">{name(e.dst)}<em>.{portName(e.dst_port)}</em></span>
            </div>
            <div class="row">
              <button disabled={busyEdges.has(e.id)} on:click={() => onDiscuss(e.id, true)}>
                拉入讨论
              </button>
            </div>
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
              <span class="ep">{d.src_name ?? name(d.src)}</span>
              <span class="arrow">→</span>
              <span class="ep">{d.dst_name ?? name(d.dst)}</span>
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
                <button disabled={busyEdges.has(d.id)} on:click={() => onDiscuss(d.id, false)}>
                  移出讨论
                </button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- §13.6 discussion chat (DiscussPanel via App.svelte) -->
  <slot />
</aside>

<style>
  /* 星图册 · 核对面板 = 漆器典籍窗（调色板见 app.css :root） */
  .verify {
    width: 340px;
    background: linear-gradient(180deg, var(--panel) 0%, #111a30 100%);
    border-left: 1px solid var(--hairline);
    box-shadow: -12px 0 28px rgba(0, 0, 0, 0.35);
    color: var(--text);
    font-size: 12px;
    overflow-y: auto;
    padding: 14px 14px 24px;
    box-sizing: border-box;
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
  section {
    margin-bottom: 20px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--hairline-2);
  }
  section:last-of-type {
    border-bottom: none;
  }
  .filter {
    font-family: var(--font-body);
    font-size: 11px;
    letter-spacing: 0;
    color: var(--amber);
  }
  .count {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 10px;
    background: var(--panel-3);
    border: 1px solid var(--hairline-2);
    border-radius: 8px;
    padding: 0 7px;
    color: var(--muted);
  }
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  li {
    border: 1px solid var(--hairline-2);
    border-radius: 6px;
    padding: 9px;
    margin-bottom: 8px;
    background: var(--panel-2);
  }
  li.ghost {
    border-left: 3px solid var(--violet);
  }
  li.dis {
    border-left: 3px solid var(--crimson);
  }
  .endpoints {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
  }
  .ep {
    color: var(--ivory);
  }
  .ep em {
    color: var(--star);
    font-style: normal;
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .arrow {
    color: var(--gold-dim);
  }
  .slice {
    font-family: var(--font-mono);
    font-size: 10px;
    color: #cfe0f2;
    background: #22334f;
    border-radius: 3px;
    padding: 1px 5px;
  }
  .citation {
    display: block;
    margin-top: 6px;
    background: var(--panel-3);
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    padding: 4px 7px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: #aebfd6;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .row {
    display: flex;
    gap: 6px;
    margin-top: 8px;
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
      color 0.15s;
  }
  button:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  button.ok {
    border-color: #3d6b52;
    color: var(--jade);
  }
  button.ok:hover {
    border-color: var(--jade);
    box-shadow: 0 0 8px rgba(126, 207, 165, 0.25);
  }
  button.danger {
    border-color: #7a4038;
    color: var(--crimson);
  }
  button.danger:hover {
    border-color: var(--crimson);
    box-shadow: 0 0 8px rgba(224, 122, 104, 0.25);
  }
  .reject-form {
    margin-top: 8px;
  }
  textarea {
    width: 100%;
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
  .reason {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-radius: 3px;
    padding: 1px 6px;
    background: #3a2f1c;
    color: var(--amber);
  }
  .reason-disputed {
    background: var(--crimson-deep);
    color: var(--crimson);
  }
  .reason-manual {
    background: #1e2c44;
    color: var(--star);
  }
  .verdict-line {
    margin-top: 6px;
    color: var(--muted);
  }
  .verdict-line b {
    color: var(--ivory);
  }
  .by {
    color: var(--gold-dim);
    margin-left: 4px;
  }
  blockquote {
    margin: 6px 0 0;
    padding: 5px 9px;
    border-left: 2px solid var(--gold-dim);
    color: var(--text);
    background: var(--panel-3);
    border-radius: 0 4px 4px 0;
  }
  .muted {
    color: var(--muted);
    margin: 4px 0;
  }
</style>
