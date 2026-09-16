<script lang="ts">
  import {
    deleteNode,
    fetchProvenance,
    renameNode,
    type FileOpenRequest,
    type ProvenanceHop,
  } from './api'
  import {
    createPort,
    deletePort,
    updatePort,
    type CreatePortRequest,
    type UpdatePortRequest,
  } from './object-authoring'
  import NodeAuthoringSection from './NodeAuthoringSection.svelte'
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
  let lastNodeId: string | null = null
  let chain: ProvenanceHop[] = []
  let chainFor: string | null = null
  let traceBusy = false
  let mutationBusy = false
  let mutationError: string | null = null

  $: currentNodeId = node?.id ?? null
  $: if (currentNodeId !== lastNodeId) {
    lastNodeId = currentNodeId
    expanded = false
    traceOpen = false
    chain = []
    chainFor = null
    mutationError = null
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

  function formatVal(v: unknown): string {
    if (typeof v === 'string') return v
    if (v === null || v === undefined) return String(v)
    if (typeof v === 'object') {
      try { return JSON.stringify(v, null, 2) } catch { return String(v) }
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

  async function runMutation(work: () => Promise<unknown>) {
    if (mutationBusy) return
    mutationBusy = true
    mutationError = null
    try {
      await work()
    } catch (err) {
      mutationError = (err as Error).message
    } finally {
      mutationBusy = false
    }
  }

  function renameCurrentNode() {
    if (!node || mutationBusy) return
    const value = window.prompt('Rename node', node.name)
    if (value === null) return
    const next = value.trim()
    if (!next || next === node.name) return
    const id = node.id
    void runMutation(() => renameNode(id, next))
  }

  function deleteCurrentNode() {
    if (!node || mutationBusy) return
    const portPart = ports.length > 0 ? ` ${ports.length} port${ports.length === 1 ? '' : 's'} will be removed.` : ''
    const childPart = node.child_count > 0 ? ` This node contains ${node.child_count} child object${node.child_count === 1 ? '' : 's'}; server policy will decide whether deletion is allowed.` : ''
    if (!window.confirm(`Delete “${node.name}”?${portPart}${childPart} Incident edges are handled by the graph transaction.`)) return
    const id = node.id
    void runMutation(() => deleteNode(id))
  }

  function createNodePort(request: CreatePortRequest) {
    if (!node) return
    const id = node.id
    void runMutation(() => createPort(id, request))
  }

  function updateNodePort(port: PortDTO, request: UpdatePortRequest) {
    void runMutation(() => updatePort(port.id, request))
  }

  function deleteNodePort(port: PortDTO) {
    if (!window.confirm(`Delete port “${port.name}”? Connected ports must be disconnected first.`)) return
    void runMutation(() => deletePort(port.id))
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

        {#if mutationError}
          <div class="mutation-error" role="status">{mutationError}</div>
        {/if}
        {#if mutationBusy}
          <div class="mutation-status">Applying graph change…</div>
        {/if}

        <NodeAuthoringSection
          {node}
          {portsById}
          {registryDescriptor}
          {onAttachPort}
          onRename={renameCurrentNode}
          onDelete={deleteCurrentNode}
          onCreatePort={createNodePort}
          onUpdatePort={updateNodePort}
          onDeletePort={deleteNodePort}
        />

        {#if node.type === 'file' || planFile || stdoutPath || stderrPath || metricsPath}
          <section>
            <h3>Files</h3>
            <div class="actions">
              {#if node.type === 'file'}<button on:click={() => onOpenFile({ node: node!.id })}>Open file</button>{/if}
              {#if planFile}<button on:click={() => onOpenFile({ path: planFile!, highlight: planLid ?? undefined })}>Source {planLid ?? ''}</button>{/if}
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
          <section><button class="done" on:click={() => onResolveNote(node!.id)}>Mark done</button></section>
        {/if}

        <details class="attrs-panel">
          <summary>Attributes {attrEntries.length > 0 ? `· ${attrEntries.length}` : ''}</summary>
          {#if attrEntries.length > 0}
            <dl>
              {#each attrEntries as [key, value]}
                <dt>{key}</dt><dd><pre>{formatVal(value)}</pre></dd>
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
    position: absolute; top: 14px; right: 14px; z-index: 22;
    display: flex; flex-direction: column; align-items: flex-end; gap: 6px;
    max-width: min(560px, calc(100% - 28px)); color: var(--text); font-size: 12px;
    pointer-events: none;
  }
  .selection-ui > * { pointer-events: auto; }
  .selection-bar {
    display: flex; align-items: center; gap: 6px; min-height: 38px; padding: 5px 6px 5px 8px;
    box-sizing: border-box; border: 1px solid var(--hairline); border-radius: 6px;
    background: rgba(12,23,38,.94); box-shadow: 0 8px 24px rgba(0,0,0,.28);
  }
  .node-mark { width: 8px; height: 8px; border: 1px solid var(--blue); background: var(--panel-3); }
  .node-mark.trusted { background: var(--amber); border-color: var(--amber); }
  .identity { min-width: 120px; max-width: 210px; display: flex; flex-direction: column; line-height: 1.15; }
  .identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ivory); font-weight: 600; }
  .identity span { margin-top: 2px; color: var(--muted); font: 9px var(--font-mono); }
  button {
    min-height: 28px; padding: 3px 8px; border: 1px solid var(--hairline); border-radius: 4px;
    background: var(--panel-2); color: var(--text); cursor: pointer; font: 10px var(--font-body);
  }
  button:hover:not(:disabled), button.active { border-color: var(--blue); color: var(--ivory); }
  button:disabled { opacity: .55; cursor: not-allowed; }
  button.primary { color: var(--violet); border-color: rgba(178,140,224,.45); }
  .context-strip {
    display: flex; align-items: center; gap: 6px; max-width: 540px; padding: 5px 7px;
    border: 1px solid var(--hairline); border-radius: 5px; background: rgba(12,23,38,.94);
  }
  .context-label { color: var(--muted); font: 8px var(--font-mono); text-transform: uppercase; }
  .context-path { display: flex; gap: 4px; overflow-x: auto; }
  .context-hop { display: flex; flex-direction: column; align-items: flex-start; min-width: 86px; }
  .context-hop span { max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .context-hop small { color: var(--muted); font: 8px var(--font-mono); }
  .details {
    width: min(540px, calc(100vw - 28px)); max-height: min(76vh, 720px); overflow: auto;
    box-sizing: border-box; padding: 10px; border: 1px solid var(--hairline); border-radius: 6px;
    background: rgba(12,23,38,.97); box-shadow: 0 12px 34px rgba(0,0,0,.34);
  }
  .detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--hairline-2); }
  .detail-head h2 { margin: 2px 0 0; color: var(--ivory); font-size: 15px; }
  .detail-head code { max-width: 220px; overflow: hidden; text-overflow: ellipsis; color: var(--muted); font: 8px var(--font-mono); }
  .eyebrow { color: var(--muted); font: 8px var(--font-mono); text-transform: uppercase; letter-spacing: .08em; }
  .details > section, .details > details, .details > :global(.authoring) { margin-top: 10px; }
  h3 { margin: 0 0 6px; color: var(--ivory); font-size: 11px; }
  .actions { display: flex; flex-wrap: wrap; gap: 5px; }
  .facts dl, .attrs-panel dl { display: grid; grid-template-columns: 72px minmax(0,1fr); gap: 4px 7px; margin: 0; }
  dt { color: var(--muted); font: 9px var(--font-mono); }
  dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
  .attrs-panel summary { cursor: pointer; color: var(--muted); font: 9px var(--font-mono); }
  pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #a9b9cf; font: 8px/1.4 var(--font-mono); }
  .mutation-error, .mutation-status { margin-top: 8px; padding: 6px 7px; border-radius: 4px; font: 9px/1.35 var(--font-mono); }
  .mutation-error { border: 1px solid rgba(238,123,115,.38); color: var(--crimson); background: rgba(238,123,115,.06); }
  .mutation-status { border: 1px solid var(--hairline-2); color: var(--muted); background: var(--panel-3); }
  .muted { color: var(--muted); font: 9px var(--font-mono); }
  .done { color: var(--jade); }
</style>
