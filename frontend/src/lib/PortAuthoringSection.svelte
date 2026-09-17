<script lang="ts">
  import PortCreateForm from './PortCreateForm.svelte'
  import PortEditor from './PortEditor.svelte'
  import { objectAction, portAction, type CreatePortRequest, type UpdatePortRequest } from './object-authoring'
  import type { NodeDTO, PortDTO, RegistryDescriptorDTO } from './types'

  export let node: NodeDTO
  export let portsById: Map<string, PortDTO>
  export let registryDescriptor: RegistryDescriptorDTO | null = null
  export let onAttachPort: (port: PortDTO) => void = () => {}
  export let onCreatePort: (request: CreatePortRequest) => void = () => {}
  export let onUpdatePort: (port: PortDTO, request: UpdatePortRequest) => void = () => {}
  export let onDeletePort: (port: PortDTO) => void = () => {}

  let inspectedPortId: string | null = null
  let createDirection: 'in' | 'out' | null = null

  $: ports = node.ports.map(id => portsById.get(id)).filter(Boolean) as PortDTO[]
  $: inputPorts = ports.filter(port => port.side === 'in')
  $: outputPorts = ports.filter(port => port.side === 'out')
  $: createAction = objectAction(node.affordances, 'port.create')

  const label = (port: PortDTO): string =>
    typeof port.attrs.label === 'string' && port.attrs.label.trim()
      ? port.attrs.label
      : port.name

  const shape = (port: PortDTO): string | null =>
    Array.isArray(port.attrs.shape) ? (port.attrs.shape as unknown[]).join('×') : null

  function summary(port: PortDTO): string {
    const parts = [port.port_type || 'any']
    const portShape = shape(port)
    if (portShape) parts.push(portShape)
    if (typeof port.attrs.confidence === 'string' && port.attrs.confidence) {
      parts.push(port.attrs.confidence)
    }
    return parts.join(' · ')
  }

  function toggleInspect(id: string) {
    inspectedPortId = inspectedPortId === id ? null : id
    createDirection = null
  }

  function beginCreate(direction: 'in' | 'out') {
    createDirection = createDirection === direction ? null : direction
    inspectedPortId = null
  }
</script>

<section class="io-section" aria-label="Node interface">
  <div class="section-head">
    <div>
      <h3>Interface</h3>
      <p>{inputPorts.length} in · {outputPorts.length} out</p>
    </div>
    {#if createAction}
      <div class="create-actions">
        <button
          disabled={!createAction.enabled}
          title={createAction.enabled ? 'Add input port' : createAction.reason}
          on:click={() => beginCreate('in')}
        >+ Input</button>
        <button
          disabled={!createAction.enabled}
          title={createAction.enabled ? 'Add output port' : createAction.reason}
          on:click={() => beginCreate('out')}
        >+ Output</button>
      </div>
    {/if}
  </div>

  {#if createAction && !createAction.enabled}
    <p class="reason">{createAction.reason}</p>
  {/if}

  {#if createDirection && createAction}
    <PortCreateForm
      direction={createDirection}
      action={createAction}
      {registryDescriptor}
      onCreate={(request) => {
        onCreatePort(request)
        createDirection = null
      }}
      onCancel={() => (createDirection = null)}
    />
  {/if}

  <div class="columns">
    {#each [
      { direction: 'in', title: 'Inputs', items: inputPorts },
      { direction: 'out', title: 'Outputs', items: outputPorts },
    ] as group}
      <div class="column">
        <h4>{group.title}</h4>
        {#if group.items.length === 0}<span class="empty">none</span>{/if}
        {#each group.items as port (port.id)}
          {@const attachAction = portAction(port, 'context.attach')}
          {@const updateAction = portAction(port, 'port.update')}
          {@const deleteAction = portAction(port, 'port.delete')}
          <div class="port" class:open={inspectedPortId === port.id}>
            <div class="row">
              <span class:input={port.side === 'in'} class:output={port.side === 'out'} class="dot"></span>
              <div class="identity">
                <strong>{label(port)}</strong>
                <small>{label(port) !== port.name ? `${port.name} · ` : ''}{summary(port)}</small>
              </div>
              <div class="row-actions">
                {#if attachAction}
                  <button
                    class="ask"
                    disabled={!attachAction.enabled}
                    title={attachAction.enabled ? 'Ask the Agent about this port' : attachAction.reason}
                    on:click={() => onAttachPort(port)}
                  >Ask</button>
                {/if}
                <button
                  class:active={inspectedPortId === port.id}
                  on:click={() => toggleInspect(port.id)}
                >Inspect</button>
              </div>
            </div>

            {#if inspectedPortId === port.id}
              <div class="inspect">
                <dl>
                  <dt>id</dt><dd><code>{port.id}</code></dd>
                  <dt>direction</dt><dd>{port.side === 'in' ? 'input' : 'output'}</dd>
                  <dt>type</dt><dd>{port.port_type || 'any'}</dd>
                </dl>
                {#if updateAction || deleteAction}
                  <PortEditor
                    {port}
                    {registryDescriptor}
                    {updateAction}
                    {deleteAction}
                    onSave={(request) => onUpdatePort(port, request)}
                    onDelete={() => onDeletePort(port)}
                  />
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/each}
  </div>
</section>

<style>
  .io-section { padding: 9px 10px; }
  .section-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
  }
  h3, h4, p { margin: 0; }
  h3 { color: var(--ivory); font-size: 11px; }
  .section-head p { margin-top: 2px; color: var(--muted); font: 8px var(--font-mono); }
  .create-actions { display: flex; gap: 4px; }
  button {
    min-height: 26px;
    padding: 3px 7px;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--text);
    cursor: pointer;
    font: 9px var(--font-body);
  }
  button:hover:not(:disabled), button.active { border-color: var(--blue); color: var(--ivory); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.ask { color: var(--violet); }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-top: 8px;
  }
  .column { min-width: 0; }
  h4 { margin-bottom: 4px; color: var(--muted); font: 8px var(--font-mono); text-transform: uppercase; }
  .port {
    margin-bottom: 5px;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: rgba(8, 20, 33, 0.42);
  }
  .port.open { border-color: rgba(76, 146, 195, 0.45); }
  .row { display: flex; align-items: center; gap: 6px; padding: 5px; }
  .dot { width: 7px; height: 7px; border: 1px solid currentColor; border-radius: 50%; flex: 0 0 auto; }
  .dot.input { color: var(--blue); }
  .dot.output { color: var(--amber); }
  .identity { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ivory); font-size: 10px; }
  .identity small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font: 8px var(--font-mono); }
  .row-actions { display: flex; gap: 3px; }
  .inspect { padding: 0 6px 6px; }
  .inspect dl { display: grid; grid-template-columns: 54px minmax(0, 1fr); gap: 3px 6px; margin: 3px 0 0; }
  .inspect dt { color: var(--muted); font: 8px var(--font-mono); }
  .inspect dd { min-width: 0; margin: 0; color: var(--text); overflow-wrap: anywhere; font-size: 9px; }
  .inspect code { font: 8px var(--font-mono); color: var(--muted); }
  .empty, .reason { color: var(--muted); font: 9px var(--font-mono); }
  .reason { margin-top: 5px; }
  @media (max-width: 720px) { .columns { grid-template-columns: 1fr; } }
</style>
