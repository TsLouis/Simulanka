<script lang="ts">
  import type { NodeDTO, PortDTO } from './types'

  export let node: NodeDTO | null
  export let portsById: Map<string, PortDTO>

  $: ports = node ? node.ports.map(id => portsById.get(id)).filter(Boolean) as PortDTO[] : []
  $: attrEntries = node ? Object.entries(node.attrs) : []

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
      <h2>{node.name}</h2>
      <code class="id">{node.id}</code>
    </header>

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
            </li>
          {/each}
        </ul>
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
