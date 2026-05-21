<script lang="ts">
  import type { NodeDTO, PortDTO } from './types'

  export let node: NodeDTO | null
  export let portsById: Map<string, PortDTO>

  $: ports = node ? node.ports.map(id => portsById.get(id)).filter(Boolean) as PortDTO[] : []
  $: attrEntries = node ? Object.entries(node.attrs) : []

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
              <span class="name">{p.name}</span>
              <span class="muted">{p.port_type}</span>
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
  .inspector {
    width: 320px;
    background: #1f1f1f;
    border-left: 1px solid #333;
    color: #ddd;
    font-size: 12px;
    overflow-y: auto;
    padding: 12px 14px 24px;
    box-sizing: border-box;
  }
  header {
    border-bottom: 1px solid #333;
    padding-bottom: 10px;
    margin-bottom: 10px;
  }
  h2 {
    margin: 6px 0 4px;
    font-size: 15px;
    color: #fff;
    word-break: break-word;
  }
  h3 {
    margin: 0 0 4px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
  }
  section {
    margin-bottom: 12px;
  }
  .type-chip {
    display: inline-block;
    background: #2c3e50;
    color: #cde;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .id {
    display: block;
    font-family: ui-monospace, monospace;
    color: #888;
    font-size: 10px;
    word-break: break-all;
  }
  .muted {
    color: #888;
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
    border-radius: 2px;
    font-size: 10px;
    text-transform: uppercase;
    padding: 1px 0;
  }
  .side-in {
    background: #2b3e2b;
    color: #aef0ae;
  }
  .side-out {
    background: #3e2b2b;
    color: #f0aeae;
  }
  .name {
    flex: 1;
  }
  .attrs {
    margin: 0;
  }
  .attrs dt {
    color: #aaa;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    margin-top: 6px;
  }
  .attrs dd {
    margin: 2px 0 0;
  }
  .attrs pre {
    margin: 0;
    background: #181818;
    border: 1px solid #2a2a2a;
    border-radius: 3px;
    padding: 4px 6px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
