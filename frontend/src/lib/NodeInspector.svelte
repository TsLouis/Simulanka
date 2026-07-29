<script lang="ts">
  import { fetchProvenance, type FileOpenRequest, type ProvenanceHop } from './api'
  import type { NodeDTO, PortDTO } from './types'

  export let node: NodeDTO | null
  export let portsById: Map<string, PortDTO>
  // S4: open the read-only file viewer. file 节点=打开自身；plan_file 深链=
  // 打开出处并高亮 lid；run 日志=打开 stdout/stderr file 节点。
  export let onOpenFile: (req: FileOpenRequest) => void = () => {}
  // S6 血缘链逐跳可点 / S7 escalate 就地已处理——动作由宿主执行。
  export let onJumpTo: (id: string) => void = () => {}
  export let onResolveNote: (id: string) => void = () => {}
  export let onAttachNode: (node: NodeDTO) => void = () => {}
  export let onAttachPort: (port: PortDTO) => void = () => {}

  $: ports = node ? node.ports.map(id => portsById.get(id)).filter(Boolean) as PortDTO[] : []
  $: attrEntries = node ? Object.entries(node.attrs) : []

  const strAttr = (n: NodeDTO | null, key: string): string | null =>
    n && typeof n.attrs[key] === 'string' ? (n.attrs[key] as string) : null

  $: planFile = strAttr(node, 'plan_file')
  $: planLid = strAttr(node, 'plan_lid')
  $: stdoutPath = strAttr(node, 'stdout_path')
  $: stderrPath = strAttr(node, 'stderr_path')
  $: metricsPath = strAttr(node, 'metrics_path')

  // S7: 未解决的 escalate note 才出「已处理」——唯一能解除停止信号的人为动作。
  $: openEscalate =
    node !== null &&
    node.type === 'note' &&
    strAttr(node, 'kind') === 'escalate' &&
    strAttr(node, 'status') !== 'resolved'

  // S6 血缘链：研究域节点（trust 非空）按需拉取；id 守卫防止 $: 重入循环。
  let chain: ProvenanceHop[] = []
  let chainFor: string | null = null
  $: if (node && node.trust && node.id !== chainFor) void loadChain(node.id)
  $: if (node === null || !node.trust) {
    chain = []
    chainFor = null
  }
  async function loadChain(id: string) {
    chainFor = id
    try {
      const c = await fetchProvenance(id)
      if (chainFor === id) chain = c
    } catch {
      if (chainFor === id) chain = []
    }
  }

  const portLabel = (p: PortDTO): string | null =>
    typeof p.attrs.label === 'string' ? p.attrs.label : null
  const portShape = (p: PortDTO): string | null =>
    Array.isArray(p.attrs.shape) ? (p.attrs.shape as number[]).join('×') : null
  const portConfidence = (p: PortDTO): string | null =>
    typeof p.attrs.confidence === 'string' ? p.attrs.confidence : null

  function formatVal(v: unknown): string {
    if (typeof v === 'string') return v
    if (v === null || v === undefined) return String(v)
    if (typeof v === 'object') {
      try {
        return JSON.stringify(v, null, 2)
      } catch {
        return String(v)
      }
    }
    return String(v)
  }
</script>

{#if node}
  <aside class="inspector">
    <header>
      <span class="type-chip">{node.type}</span>
      {#if node.trust}
        <span class="trust-chip t-{node.trust}">{node.trust}</span>
      {/if}
      <h2>{node.name}</h2>
      <code class="id">{node.id}</code>
      <button class="attach-btn" on:click={() => onAttachNode(node!)}>
        ＋ 附加节点
      </button>
    </header>

    {#if openEscalate}
      <section>
        <button class="resolve-btn" on:click={() => onResolveNote(node!.id)}>
          ✓ 已处理
        </button>
      </section>
    {/if}

    {#if node.type === 'file' || planFile || stdoutPath || stderrPath || metricsPath}
      <section>
        <h3>Files</h3>
        <div class="file-actions">
          {#if node.type === 'file'}
            <button class="file-btn" on:click={() => onOpenFile({ node: node!.id })}>
              📄 打开文件
            </button>
          {/if}
          {#if planFile}
            <button
              class="file-btn"
              title={planFile + (planLid ? ` · ${planLid}` : '')}
              on:click={() =>
                onOpenFile({ path: planFile!, highlight: planLid ?? undefined })}
            >
              ↗ 出处 {planLid ?? ''}
            </button>
          {/if}
          {#if stdoutPath}
            <button class="file-btn" on:click={() => onOpenFile({ path: stdoutPath! })}>
              stdout
            </button>
          {/if}
          {#if stderrPath}
            <button class="file-btn" on:click={() => onOpenFile({ path: stderrPath! })}>
              stderr
            </button>
          {/if}
          {#if metricsPath}
            <button class="file-btn" on:click={() => onOpenFile({ path: metricsPath! })}>
              metrics
            </button>
          {/if}
        </div>
      </section>
    {/if}

    {#if node.parent_id}
      <section>
        <h3>Parent</h3>
        <code class="id">{node.parent_id}</code>
      </section>
    {/if}

    {#if node.child_count > 0}
      <section>
        <h3>Children</h3>
        <span class="muted">{node.child_count} (double-click node to drill in)</span>
      </section>
    {/if}

    {#if ports.length > 0}
      <section>
        <h3>Ports</h3>
        <ul class="ports">
          {#each ports as p (p.id)}
            <li>
              <span class="side side-{p.side}">{p.side}</span>
              <span class="name">
                {portLabel(p) ?? p.name}
                {#if portLabel(p)}<span class="slotname">{p.name}</span>{/if}
              </span>
              {#if portShape(p)}<span class="shape">{portShape(p)}</span>{/if}
              {#if portConfidence(p)}
                <span class="conf conf-{portConfidence(p)}">{portConfidence(p)}</span>
              {/if}
              <button
                class="port-attach"
                title={`附加端口 ${p.id}`}
                aria-label={`附加端口 ${portLabel(p) ?? p.name}`}
                on:click={() => onAttachPort(p)}
              >＋</button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if chain.length > 1}
      <section>
        <h3>血缘链</h3>
        <div class="chain">
          {#each chain.slice(1) as hop (hop.id)}
            <button class="hop" on:click={() => onJumpTo(hop.id)} title={hop.id}>
              <span class="via">
                ↳ {hop.via_edge}
                {#if hop.via_edge_trust}
                  <i class="t-chip t-{hop.via_edge_trust}">{hop.via_edge_trust}</i>
                {/if}
              </span>
              <span class="hop-main">
                <span class="hop-type">{hop.type}</span>
                <span class="hop-name">{hop.name}</span>
                {#if hop.trust}
                  <i class="t-chip t-{hop.trust}">{hop.trust}</i>
                {/if}
              </span>
            </button>
          {/each}
        </div>
      </section>
    {:else if node.trust && chainFor === node.id}
      <section>
        <h3>血缘链</h3>
        <span class="muted">(无上游)</span>
      </section>
    {/if}

    {#if attrEntries.length > 0}
      <section>
        <h3>Attrs</h3>
        <dl class="attrs">
          {#each attrEntries as [k, v]}
            <dt>{k}</dt>
            <dd><pre>{formatVal(v)}</pre></dd>
          {/each}
        </dl>
      </section>
    {:else}
      <section>
        <h3>Attrs</h3>
        <span class="muted">(none)</span>
      </section>
    {/if}
  </aside>
{/if}

<style>
  /* 星图册 · 星卡详览 —— 选中一颗星，翻开它那页典籍（调色板见 app.css :root） */
  .inspector {
    width: 320px;
    background: linear-gradient(180deg, var(--panel) 0%, #111a30 100%);
    border-left: 1px solid var(--hairline);
    box-shadow: -12px 0 28px rgba(0, 0, 0, 0.35);
    color: var(--text);
    font-size: 12px;
    overflow-y: auto;
    padding: 14px 14px 24px;
    box-sizing: border-box;
  }
  header {
    position: relative;
    border-bottom: 1px solid var(--hairline-2);
    padding-bottom: 10px;
    margin-bottom: 12px;
  }
  header::after {
    content: '';
    position: absolute;
    left: 0;
    bottom: -1px;
    width: 56px;
    height: 1px;
    background: var(--gold);
  }
  h2 {
    margin: 6px 0 4px;
    font-family: var(--font-display);
    font-size: 17px;
    font-weight: 400;
    color: var(--ivory);
    word-break: break-word;
  }
  h3 {
    margin: 0 0 5px;
    font-family: var(--font-display);
    font-size: 12px;
    font-weight: 400;
    letter-spacing: 0.12em;
    color: var(--gold);
  }
  h3::before {
    content: '✦ ';
    font-size: 8px;
    color: var(--gold-dim);
  }
  .attach-btn {
    margin-top: 8px;
    border: 1px solid var(--hairline);
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--gold-bright);
    padding: 4px 8px;
    cursor: pointer;
    font: inherit;
  }
  .attach-btn:hover,
  .port-attach:hover {
    border-color: var(--gold);
  }
  .port-attach {
    margin-left: auto;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-3);
    color: var(--gold-bright);
    cursor: pointer;
  }
  section {
    margin-bottom: 14px;
  }
  .type-chip {
    display: inline-block;
    background: var(--panel-2);
    border: 1px solid var(--gold-dim);
    color: var(--gold);
    padding: 1px 7px;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  /* S6 可信五色（= theme.ts TRUST_COLORS） */
  .trust-chip,
  .t-chip {
    display: inline-block;
    border-radius: 3px;
    font-size: 9px;
    font-style: normal;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 1px 5px;
    margin-left: 5px;
    border: 1px solid currentColor;
    background: var(--panel-3);
  }
  .t-human {
    color: var(--amber);
  }
  .t-constructed {
    color: var(--star);
  }
  .t-reviewed {
    color: var(--jade);
  }
  .t-checked {
    color: var(--gold);
  }
  .t-unreviewed {
    color: var(--muted);
  }
  .resolve-btn {
    width: 100%;
    background: var(--jade-deep);
    color: var(--jade);
    border: 1px solid var(--jade);
    border-radius: 4px;
    padding: 6px 10px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    transition: box-shadow 0.15s;
  }
  .resolve-btn:hover {
    box-shadow: 0 0 8px rgba(126, 207, 165, 0.4);
  }
  .chain {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .hop {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 3px 6px;
    text-align: left;
    cursor: pointer;
    font: inherit;
    color: var(--text);
  }
  .hop:hover {
    background: var(--panel-2);
  }
  .hop .via {
    display: block;
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .hop-main {
    display: flex;
    align-items: center;
    gap: 5px;
    padding-left: 12px;
  }
  .hop-type {
    color: var(--gold-dim);
    font-size: 10px;
    text-transform: uppercase;
  }
  .hop-name {
    color: var(--ivory);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .id {
    display: block;
    font-family: var(--font-mono);
    color: var(--muted);
    font-size: 10px;
    word-break: break-all;
  }
  .muted {
    color: var(--muted);
  }
  .file-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .file-btn {
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 4px;
    padding: 3px 10px;
    cursor: pointer;
    font-family: inherit;
    font-size: 11px;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  .file-btn:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  .ports {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .ports li {
    display: flex;
    gap: 6px;
    align-items: center;
    padding: 2px 0;
  }
  .side {
    display: inline-block;
    width: 28px;
    text-align: center;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    padding: 1px 0;
  }
  .side-in {
    background: var(--jade-deep);
    color: var(--jade);
  }
  .side-out {
    background: #3a2f1c;
    color: var(--amber);
  }
  .name {
    flex: 1;
    color: var(--ivory);
  }
  .slotname {
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .shape {
    font-family: var(--font-mono);
    font-size: 10px;
    color: #cfe0f2;
    background: #22334f;
    border-radius: 3px;
    padding: 1px 5px;
  }
  .conf {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-radius: 3px;
    padding: 1px 5px;
  }
  .conf-verified {
    background: var(--jade-deep);
    color: var(--jade);
  }
  .conf-inferred {
    background: #2c3550;
    color: var(--muted);
  }
  .attrs {
    margin: 0;
  }
  .attrs dt {
    color: var(--gold-dim);
    font-family: var(--font-mono);
    font-size: 11px;
    margin-top: 7px;
  }
  .attrs dd {
    margin: 2px 0 0;
  }
  .attrs pre {
    margin: 0;
    background: var(--panel-3);
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    padding: 5px 7px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: #aebfd6;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
