<script lang="ts">
  import type { AffordanceDTO, PortDTO, RegistryDescriptorDTO } from './types'
  import {
    allowedPortTypes,
    draftFromPort,
    updateRequestFromDraft,
    validatePortDraft,
    type PortEditDraft,
  } from './port-authoring'
  import type { UpdatePortRequest } from './object-authoring'

  export let port: PortDTO
  export let registryDescriptor: RegistryDescriptorDTO | null = null
  export let updateAction: AffordanceDTO | null = null
  export let deleteAction: AffordanceDTO | null = null
  export let onSave: (request: UpdatePortRequest) => void = () => {}
  export let onDelete: () => void = () => {}

  let lastPortId = ''
  let draft: PortEditDraft = draftFromPort(port)

  $: if (port.id !== lastPortId) {
    lastPortId = port.id
    draft = draftFromPort(port)
  }
  $: types = allowedPortTypes(registryDescriptor)
  $: validation = validatePortDraft(draft, registryDescriptor)
  $: updateEnabled = updateAction?.enabled === true
  $: deleteEnabled = deleteAction?.enabled === true

  function submit() {
    if (!updateEnabled || !validation.valid) return
    onSave(updateRequestFromDraft(port, draft))
  }
</script>

<div class="editor" aria-label="Edit port">
  <label>
    <span>Name</span>
    <input bind:value={draft.name} disabled={!updateEnabled} />
  </label>

  <div class="pair">
    <label>
      <span>Direction</span>
      <select bind:value={draft.direction} disabled={!updateEnabled}>
        <option value="in">Input</option>
        <option value="out">Output</option>
      </select>
    </label>
    <label>
      <span>Type</span>
      <select bind:value={draft.portType} disabled={!updateEnabled}>
        {#each types as type}
          <option value={type}>{type}</option>
        {/each}
      </select>
    </label>
  </div>

  <label>
    <span>Label</span>
    <input bind:value={draft.label} disabled={!updateEnabled} placeholder="optional display label" />
  </label>

  <div class="pair">
    <label>
      <span>Shape</span>
      <input bind:value={draft.shape} disabled={!updateEnabled} placeholder="e.g. 1×3×224×224" />
    </label>
    <label>
      <span>Confidence</span>
      <input bind:value={draft.confidence} disabled={!updateEnabled} placeholder="optional" />
    </label>
  </div>

  {#if !updateEnabled && updateAction}
    <p class="reason">{updateAction.reason}</p>
  {:else if !validation.valid}
    <p class="reason">{validation.reason}</p>
  {/if}

  <div class="actions">
    <button class="save" disabled={!updateEnabled || !validation.valid} on:click={submit}>Save changes</button>
    {#if deleteAction}
      <button
        class="delete"
        disabled={!deleteEnabled}
        title={deleteEnabled ? 'Delete this port' : deleteAction.reason}
        on:click={onDelete}
      >Delete port</button>
    {/if}
  </div>

  {#if deleteAction && !deleteEnabled}
    <p class="reason">{deleteAction.reason}</p>
  {/if}
</div>

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: 7px;
    margin-top: 7px;
    padding: 8px;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: rgba(8, 20, 33, 0.52);
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  label > span {
    color: var(--muted);
    font: 8px var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  input,
  select {
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
  input:focus,
  select:focus { border-color: var(--blue); }
  input:disabled,
  select:disabled { opacity: 0.55; cursor: not-allowed; }
  .actions {
    display: flex;
    gap: 6px;
    margin-top: 2px;
  }
  button {
    min-height: 28px;
    padding: 4px 8px;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--text);
    cursor: pointer;
    font: 10px var(--font-body);
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .save:not(:disabled):hover { border-color: var(--blue); color: var(--ivory); }
  .delete { margin-left: auto; color: var(--crimson); }
  .delete:not(:disabled):hover { border-color: var(--crimson); }
  .reason {
    margin: 0;
    color: var(--muted);
    font: 9px/1.35 var(--font-mono);
  }
</style>
