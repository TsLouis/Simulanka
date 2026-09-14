<script lang="ts">
  import { fetchProvenance, type FileOpenRequest, type ProvenanceHop } from './api'
  import { orderedAttributeEntries, resolveNodePresentation } from './presentation'
  import type { NodeDTO, PortDTO, RegistryDescriptorDTO } from './types'

  export let node: NodeDTO | null
  export let portsById: Map<string, PortDTO>
  export let registryDescriptor: RegistryDescriptorDTO | null = null
  export let onOpenFile: (req: FileOpenRequest) => void = () => {}
  export let onJumpTo: (id: string) => void = () => {}
  export let onResolveNote: (id: string) => void = () => {}
  export let onAttachNode: (node: NodeDTO) => void = () => {}
  export let onAttachPort: (port: PortDTO) => void = () => {}

  export let expanded = false
  let traceOpen = false
  let inspectedPortId: string | null = null
  let lastNodeId: string | null = null
  let chain: ProvenanceHop[] = []
  let chainFor: string | null = null
  let traceBusy = false

  $: currentNodeId = node?.id ?? null
  $: if (currentNodeId !== lastNodeId) {
    lastNodeId = currentNodeId
    expanded = false
    traceOpen = false
    inspectedPortId = null
    chain = []
    chainFor = null
  }

  $: ports = node
    ? (node.ports.map(id => portsById.get(id)).filter(Boolean) as PortDTO[])
    : []
  $: inputPorts = ports.filter(port => port.side === 'in')
  $: outputPorts = ports.filter(port => port.side === 'out')
  $: presentation = node ? resolveNodePresentation(registryDescriptor, node.type) : null
  $: attrEntries = node
    ? orderedAttributeEntries(node.attrs, presentation?.inspector_fields ?? [])
    : []
  $: nodeAttachAction = node?.affordances.find(action => action.id === 'context.attach') ?? null

  const portAttachAction = (port: PortDTO) =>
    port.affordances.find(action => action.id === 'context.attach') ?? null

  const strAttr = (n: NodeDTO | null, key: string): string | null =>
    n && typeof n.attrs[key] === 'string' ? (n.attrs[key] as string) : null

  $: planFile = strAttr(node, 'plan_file')
  $: planLid = strAttr(node, 'plan_lid')
  $: stdoutPath = strAttr(node, 'stdout_path')
  $: stderrPath = strAttr(node, 'stderr_path')
  $: metricsPath = strAttr(node, 'metrics_path')
  $: openEscalate =
    node !== null &&
    node.type === 'note' &&
    strAttr(node, 'kind') === 'escalate' &&
    strAttr(node, 'status') !== 'resolved'

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

  async function toggleTrace() {
    traceOpen = !traceOpen
    if (!traceOpen || !node || chainFor === node.id) return
    traceBusy = true
    const id = node.id
    chainFor = id
    try {
      const result = await fetchProvenance(id)
      if (node?.id === id) chain = result
    } catch {
      if (node?.id === id) chain = []
    } finally {
      if (node?.id === id) traceBusy = false
    }
  }

  function togglePortInspect(portId: string) {
    inspectedPortId = inspectedPortId === portId ? null : portId
  }
</script>

{#if node}
  <div class="selection-ui" class:expanded>
    <div class="selection-bar">
      <span class="node-mark" class:trusted={node.trust !== null} title={node.trust ?? node.type}></span>
      <div class="identity">
        <strong>{node.name}</strong>
        <span>{node.type} · {inputPorts.length} in / {outputPorts.length} out</span>
      </div>
      {#if nodeAttachAction}
        <button
          class="primary"
          disabled={!nodeAttachAction.enabled}
          title={nodeAttachAction.enabled ? 'Ask the Agent about this node' : nodeAttachAction.reason}
          on:click={() => onAttachNode(node!)}
        >✦ Ask</button>
      {/if}
      <button
        class:active={traceOpen}
        aria-expanded={traceOpen}
        on:click={() => void toggleTrace()}
        title="Trace this node through deterministic graph provenance"
      >Trace</button>
      <button
        class:active={expanded}
        aria-expanded={expanded}
        on:click={() => (expanded = !expanded)}
        title="Inspect this node's interface and details"
      >Inspect</button>
    </div>

    {#if traceOpen}
      <section class="context-strip" aria-label="Node trace">
        {#if traceBusy}
          <span class="muted">Tracing…</span>
        {:else if chain.length > 1}
          <span class="context-label">Trace</span>
          <div class="context-path">
            {#each chain.slice(1) as hop (hop.id)}
              <button class="context-hop" on:click={() => onJumpTo(hop.id)} title={`${hop.via_edge} · ${hop.id}`}>
                <span>{hop.name}</span>
                <small>{hop.via_edge}</small>
              </button>
            {/each}
          </div>
        {:else}
          <span class="muted">No upstream trace.</span>
        {/if}
      </section>
    {/if}

    {#if expanded}
      <aside class="details" aria-label="Node inspector">
        <div class="detail-head">
          <div>
            <span class="eyebrow">{presentation?.category ?? 'node'}</span>
            <h2>{node.name}</h2>
          </div>
          <code title={node.id}>{node.id}</code>
        </div>

        {#if inputPorts.length > 0 || outputPorts.length > 0}
          <section class="io-section">
            <h3>Interface</h3>
            <div class="io-columns">
              <div>
                <h4>IN · {inputPorts.length}</h4>
                {#if inputPorts.length === 0}<span class="muted">none</span>{/if}
                {#each inputPorts as port (port.id)}
                  {@const attachAction = portAttachAction(port)}
                  {@const shape = portShape(port)}
                  {@const confidence = portConfidence(port)}
                  <div class="port-item" class:inspecting={inspectedPortId === port.id}>
                    <div class="port-row">
                      <span class="port-dot in"></span>
                      <div class="port-name">
                        <strong>{portLabel(port) ?? port.name}</strong>
                        <small>
                          {portLabel(port) ? `${port.name} · ` : ''}{port.port_type || 'any'}{shape ? ` · ${shape}` : ''}{confidence ? ` · ${confidence}` : ''}
                        </small>
                      </div>
                      <div class="port-actions">
                        {#if attachAction}
                          <button
                            class="port-action ask"
                            disabled={!attachAction.enabled}
                            title={attachAction.enabled ? 'Ask the Agent about this input' : attachAction.reason}
                            on:click={() => onAttachPort(port)}
                          >Ask</button>
                        {/if}
                        <button
                          class="port-action"
                          class:active={inspectedPortId === port.id}
                          aria-expanded={inspectedPortId === port.id}
                          on:click={() => togglePortInspect(port.id)}
                        >Inspect</button>
                      </div>
                    </div>
                    {#if inspectedPortId === port.id}
                      <div class="port-inspect">
                        <dl>
                          <dt>id</dt><dd><code>{port.id}</code></dd>
                          <dt>direction</dt><dd>input</dd>
                          <dt>type</dt><dd>{port.port_type || 'any'}</dd>
                          {#if shape}<dt>shape</dt><dd>{shape}</dd>{/if}
                          {#if confidence}<dt>confidence</dt><dd>{confidence}</dd>{/if}
                        </dl>
                        {#if Object.keys(port.attrs).length > 0}
                          <pre>{formatVal(port.attrs)}</pre>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
              <div>
                <h4>OUT · {outputPorts.length}</h4>
                {#if outputPorts.length === 0}<span class="muted">none</span>{/if}
                {#each outputPorts as port (port.id)}
                  {@const attachAction = portAttachAction(port)}
                  {@const shape = portShape(port)}
                  {@const confidence = portConfidence(port)}
                  <div class="port-item" class:inspecting={inspectedPortId === port.id}>
                    <div class="port-row">
                      <span class="port-dot out"></span>
                      <div class="port-name">
                        <strong>{portLabel(port) ?? port.name}</strong>
                        <small>
                          {portLabel(port) ? `${port.name} · ` : ''}{port.port_type || 'any'}{shape ? ` · ${shape}` : ''}{confidence ? ` · ${confidence}` : ''}
                        </small>
                      </div>
                      <div class="port-actions">
                        {#if attachAction}
                          <button
                            class="port-action ask"
                            disabled={!attachAction.enabled}
                            title={attachAction.enabled ? 'Ask the Agent about this output' : attachAction.reason}
                            on:click={() => onAttachPort(port)}
                          >Ask</button>
                        {/if}
                        <button
                          class="port-action"
                          class:active={inspectedPortId === port.id}
                          aria-expanded={inspectedPortId === port.id}
                          on:click={() => togglePortInspect(port.id)}
                        >Inspect</button>
                      </div>
                    </div>
                    {#if inspectedPortId === port.id}
                      <div class="port-inspect">
                        <dl>
                          <dt>id</dt><dd><code>{port.id}</code></dd>
                          <dt>direction</dt><dd>output</dd>
                          <dt>type</dt><dd>{port.port_type || 'any'}</dd>
                          {#if shape}<dt>shape</dt><dd>{shape}</dd>{/if}
                          {#if confidence}<dt>confidence</dt><dd>{confidence}</dd>{/if}
                        </dl>
                        {#if Object.keys(port.attrs).length > 0}
                          <pre>{formatVal(port.attrs)}</pre>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          </section>
        {/if}

        {#if node.type === 'file' || planFile || stdoutPath || stderrPath || metricsPath}
          <section>
            <h3>Files</h3>
            <div class="actions">
              {#if node.type === 'file'}
                <button on:click={() => onOpenFile({ node: node!.id })}>Open file</button>
              {/if}
              {#if planFile}
                <button on:click={() => onOpenFile({ path: planFile!, highlight: planLid ?? undefined })}>
                  Source {planLid ?? ''}
                </button>
              {/if}
              {#if stdoutPath}<button on:click={() => onOpenFile({ path: stdoutPath! })}>stdout</button>{/if}
              {#if stderrPath}<button on:click={() => onOpenFile({ path: stderrPath! })}>stderr</button>{/if}
              {#if metricsPath}<button on:click={() => onOpenFile({ path: metricsPath! })}>metrics</button>{/if}
            </div>
          </section>
        {/if}

        <section class="facts">
          <h3>Details</h3>
          <dl>
            {#if node.parent_id}<dt>parent</dt><dd>{node.parent_id}</dd>{/if}
            {#if node.child_count > 0}<dt>children</dt><dd>{node.child_count}</dd>{/if}
            {#if node.trust}<dt>trust</dt><dd>{node.trust}</dd>{/if}
          </dl>
        </section>

        {#if openEscalate}
          <section>
            <button class="done" on:click={() => onResolveNote(node!.id)}>Mark done</button>
          </section>
        {/if}

        <details class="attrs-panel">
          <summary>Attributes {attrEntries.length > 0 ? `· ${attrEntries.length}` : ''}</summary>
          {#if attrEntries.length > 0}
            <dl>
              {#each attrEntries as [key, value]}
                <dt>{key}</dt>
                <dd><pre>{formatVal(value)}</pre></dd>
              {/each}
            </dl>
          {:else}
            <span class="muted">none</span>
          {/if}
        </details>
      </aside>
    {/if}
  </div>
{/if}

<style>
  .selection-ui {
    position: absolute;
    top: 14px;
    right: 14px;
    z-index: 22;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
    max-width: min(520px, calc(100% - 28px));
    color: var(--text);
    font-size: 12px;
    pointer-events: none;
  }
  .selection-ui > * { pointer-events: auto; }
  .selection-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 38px;
    padding: 5px 6px 5px 8px;
    box-sizing: border-box;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: rgba(12, 23, 38, 0.94);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
  }
  .node-mark {
    width: 8px;
    height: 8px;
    border: 1px solid var(--blue);
    background: var(--panel-3);
  }
  .node-mark.trusted { background: var(--amber); border-color: var(--amber); }
  .identity {
    min-width: 120px;
    max-width: 210px;
    display: flex;
    flex-direction: column;
    line-height: 1.15;
  }
  .identity strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ivory);
    font-weight: 600;
  }
  .identity span {
    margin-top: 2px;
    color: var(--muted);
    font: 9px var(--font-mono);
  }
  button {
    min-height: 28px;
    padding: 3px 8px;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--text);
    cursor: pointer;
    font: 11px var(--font-body);
  }
  button:hover:not(:disabled),
  button.active {
    border-color: var(--blue);
    color: var(--ivory);
  }
  button.primary {
    border-color: rgba(178, 140, 224, 0.5);
    color: var(--violet);
  }
  button:disabled { opacity: 0.45; cursor: default; }
  .context-strip,
  .details {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: rgba(12, 23, 38, 0.97);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.34);
  }
  .context-strip { padding: 7px 8px; }
  .context-label {
    display: block;
    margin-bottom: 5px;
    color: var(--muted);
    font: 9px var(--font-mono);
    text-transform: uppercase;
  }
  .context-path { display: flex; flex-wrap: wrap; gap: 4px; }
  .context-hop {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    max-width: 160px;
    padding: 4px 6px;
  }
  .context-hop span {
    max-width: 145px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .context-hop small { color: var(--muted); font: 9px var(--font-mono); }
  .details {
    max-height: calc(100vh - 120px);
    overflow: auto;
    padding: 12px;
  }
  .detail-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--hairline-2);
  }
  .eyebrow {
    color: var(--muted);
    font: 9px var(--font-mono);
    text-transform: uppercase;
  }
  h2 {
    margin: 3px 0 0;
    color: var(--ivory);
    font: 600 16px var(--font-body);
  }
  .detail-head code {
    max-width: 130px;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--muted);
    font-size: 9px;
  }
  section { margin-top: 12px; }
  h3,
  h4 {
    margin: 0;
    color: var(--muted);
    font: 10px var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  h3 { margin-bottom: 7px; }
  h4 { margin-bottom: 5px; font-size: 9px; }
  .io-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .port-item {
    border-bottom: 1px solid rgba(43, 59, 96, 0.35);
  }
  .port-item.inspecting { background: rgba(105, 184, 242, 0.035); }
  .port-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 34px;
  }
  .port-dot {
    flex: 0 0 auto;
    width: 6px;
    height: 6px;
    border: 1px solid currentColor;
  }
  .port-dot.in { color: var(--blue); background: var(--blue); }
  .port-dot.out { color: var(--amber); background: var(--amber); }
  .port-name {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  .port-name strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
    font-size: 10px;
    font-weight: 500;
  }
  .port-name small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font: 8px var(--font-mono);
  }
  .port-actions {
    display: flex;
    flex: 0 0 auto;
    gap: 3px;
  }
  .port-action {
    min-width: auto;
    min-height: 22px;
    padding: 1px 5px;
    font-size: 9px;
  }
  .port-action.ask { color: var(--violet); }
  .port-inspect {
    padding: 6px 6px 8px 12px;
    border-top: 1px solid rgba(43, 59, 96, 0.24);
  }
  .port-inspect dl {
    display: grid;
    grid-template-columns: 62px minmax(0, 1fr);
    gap: 3px 6px;
    margin: 0;
  }
  .port-inspect code { font: 8px var(--font-mono); color: var(--muted); }
  .port-inspect pre {
    margin: 7px 0 0;
    padding: 5px 6px;
    max-height: 110px;
    overflow: auto;
    border: 1px solid var(--hairline-2);
    border-radius: 3px;
    background: var(--panel-3);
    color: #a9b9cf;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: 8px/1.4 var(--font-mono);
  }
  .actions { display: flex; flex-wrap: wrap; gap: 5px; }
  .facts dl,
  .attrs-panel dl {
    display: grid;
    grid-template-columns: 72px 1fr;
    gap: 4px 8px;
    margin: 0;
  }
  dt { color: var(--muted); font: 9px var(--font-mono); }
  dd {
    min-width: 0;
    margin: 0;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .done {
    width: 100%;
    border-color: rgba(126, 207, 165, 0.5);
    color: var(--jade);
  }
  .attrs-panel {
    margin-top: 12px;
    padding-top: 9px;
    border-top: 1px solid var(--hairline-2);
  }
  .attrs-panel summary {
    cursor: pointer;
    color: var(--muted);
    font: 10px var(--font-mono);
  }
  .attrs-panel dl { margin-top: 8px; }
  .attrs-panel pre {
    margin: 0;
    padding: 4px 6px;
    border: 1px solid var(--hairline-2);
    border-radius: 3px;
    background: var(--panel-3);
    color: #a9b9cf;
    white-space: pre-wrap;
    word-break: break-word;
    font: 9px/1.4 var(--font-mono);
  }
  .muted { color: var(--muted); font-size: 10px; }
  @media (max-width: 760px) {
    .selection-ui { left: 12px; right: 12px; max-width: none; }
    .selection-bar { width: 100%; }
    .identity { flex: 1; }
    .details { max-height: calc(100vh - 150px); }
    .io-columns { grid-template-columns: 1fr; }
  }
</style>
