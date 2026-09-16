<script lang="ts">
  import type { AffordanceDTO } from './types'

  export let renameAction: AffordanceDTO | null = null
  export let deleteAction: AffordanceDTO | null = null
  export let disconnectAction: AffordanceDTO | null = null
  export let onRename: () => void = () => {}
  export let onDelete: () => void = () => {}
  export let onDisconnect: () => void = () => {}

  const titleFor = (action: AffordanceDTO): string =>
    action.enabled ? action.label : action.reason
</script>

{#if renameAction || deleteAction || disconnectAction}
  <section class="structural" aria-label="Structure actions">
    <div class="head">
      <span>Structure</span>
      <small>server-authorized</small>
    </div>
    <div class="actions">
      {#if renameAction}
        <button
          disabled={!renameAction.enabled}
          title={titleFor(renameAction)}
          on:click={onRename}
        >Rename</button>
      {/if}
      {#if disconnectAction}
        <button
          class="danger"
          disabled={!disconnectAction.enabled}
          title={titleFor(disconnectAction)}
          on:click={onDisconnect}
        >Disconnect</button>
      {/if}
      {#if deleteAction}
        <button
          class="danger"
          disabled={!deleteAction.enabled}
          title={titleFor(deleteAction)}
          on:click={onDelete}
        >Delete</button>
      {/if}
    </div>
    {#each [renameAction, disconnectAction, deleteAction].filter(Boolean) as action}
      {#if action && !action.enabled}
        <p class="reason"><strong>{action.label}:</strong> {action.reason}</p>
      {/if}
    {/each}
  </section>
{/if}

<style>
  .structural {
    padding-top: 8px;
    border-top: 1px solid var(--hairline-2);
  }
  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
  }
  .head span {
    color: var(--ivory);
    font: 10px var(--font-body);
    font-weight: 600;
  }
  .head small {
    color: var(--muted);
    font: 8px var(--font-mono);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
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
  button:hover:not(:disabled) { border-color: var(--blue); color: var(--ivory); }
  button.danger { color: var(--crimson); }
  button.danger:hover:not(:disabled) { border-color: var(--crimson); }
  button:disabled { opacity: 0.52; cursor: not-allowed; }
  .reason {
    margin: 5px 0 0;
    color: var(--muted);
    font: 9px/1.35 var(--font-mono);
  }
  .reason strong { color: var(--text); font-weight: 500; }
</style>
