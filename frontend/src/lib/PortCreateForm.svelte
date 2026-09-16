<script lang="ts">
  import type { AffordanceDTO, RegistryDescriptorDTO } from './types'
  import { allowedPortTypes } from './port-authoring'
  import type { CreatePortRequest } from './object-authoring'

  export let direction: 'in' | 'out'
  export let action: AffordanceDTO | null = null
  export let registryDescriptor: RegistryDescriptorDTO | null = null
  export let onCreate: (request: CreatePortRequest) => void = () => {}
  export let onCancel: () => void = () => {}

  let name = ''
  let portType = 'any'
  $: types = allowedPortTypes(registryDescriptor)
  $: if (!types.includes(portType)) portType = types[0] ?? 'any'
  $: enabled = action?.enabled === true
  $: valid = name.trim().length > 0 && types.includes(portType)

  function submit() {
    if (!enabled || !valid) return
    onCreate({ name: name.trim(), direction, port_type: portType })
  }
</script>

<div class="create-form" aria-label={`Add ${direction === 'in' ? 'input' : 'output'} port`}>
  <div class="title">Add {direction === 'in' ? 'input' : 'output'}</div>
  <div class="fields">
    <input bind:value={name} disabled={!enabled} placeholder="Port name" on:keydown={(event) => {
      if (event.key === 'Enter') submit()
      if (event.key === 'Escape') onCancel()
    }} />
    <select bind:value={portType} disabled={!enabled}>
      {#each types as type}<option value={type}>{type}</option>{/each}
    </select>
  </div>
  {#if action && !enabled}<p>{action.reason}</p>{/if}
  <div class="actions">
    <button disabled={!enabled || !valid} on:click={submit}>Add</button>
    <button class="quiet" on:click={onCancel}>Cancel</button>
  </div>
</div>

<style>
  .create-form {
    margin-top: 6px;
    padding: 7px;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: rgba(8, 20, 33, 0.5);
  }
  .title { margin-bottom: 5px; color: var(--ivory); font: 10px var(--font-body); }
  .fields { display: grid; grid-template-columns: minmax(0, 1fr) 92px; gap: 5px; }
  input, select {
    min-width: 0;
    box-sizing: border-box;
    padding: 5px 6px;
    border: 1px solid var(--hairline);
    border-radius: 3px;
    background: var(--panel-2);
    color: var(--text);
    font: 10px var(--font-mono);
    outline: none;
  }
  input:focus, select:focus { border-color: var(--blue); }
  .actions { display: flex; gap: 5px; margin-top: 6px; }
  button {
    min-height: 26px;
    padding: 3px 8px;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--text);
    cursor: pointer;
    font: 9px var(--font-body);
  }
  button:hover:not(:disabled) { border-color: var(--blue); color: var(--ivory); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.quiet { color: var(--muted); }
  p { margin: 5px 0 0; color: var(--muted); font: 9px/1.35 var(--font-mono); }
</style>
