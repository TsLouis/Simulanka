<script lang="ts">
  export let inspectorOpen = false
  export let canInspect = false
  export let registryOpen = false
  export let filesOpen = false
  export let canOpenFile = false
  export let discussionOpen = false
  export let recoveryOpen = false
  export let onInspector: () => void
  export let onRegistry: () => void
  export let onFiles: () => void
  export let onDiscussion: () => void
  export let onRecovery: () => void
</script>

<nav aria-label="Workspace surfaces">
  <button aria-label="Inspector" title={canInspect ? 'Inspector · selected node details' : 'Select a node to Inspect'}
    aria-expanded={inspectorOpen} class:active={inspectorOpen} disabled={!canInspect} on:click={onInspector}>i</button>
  <button aria-label="Registry" title="Registry" aria-expanded={registryOpen}
    class:active={registryOpen} on:click={onRegistry}>▦</button>
  <button aria-label="Files" title={canOpenFile ? 'Files · selected or last opened file' : 'Open a related file from Inspect'}
    aria-expanded={filesOpen} class:active={filesOpen} disabled={!canOpenFile} on:click={onFiles}>▤</button>
  <button aria-label="Discussion" title="Discussion" aria-expanded={discussionOpen}
    class:active={discussionOpen} on:click={onDiscussion}>✦</button>
  <button aria-label="Session recovery" title="Session recovery" aria-expanded={recoveryOpen}
    class:active={recoveryOpen} on:click={onRecovery}>↺</button>
</nav>

<style>
  nav {
    flex: 0 0 42px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding-top: 10px;
    background: var(--workspace-bg);
    border-right: 1px solid var(--hairline-2);
  }
  button {
    width: 32px;
    height: 32px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 3px;
    background: transparent;
    color: var(--muted);
    font: 18px var(--font-body);
    cursor: pointer;
  }
  button:hover:not(:disabled), button.active {
    color: var(--blue);
    border-color: var(--hairline);
    background: var(--panel);
  }
  button:focus-visible { outline: 1px solid var(--blue); outline-offset: 2px; }
  button:disabled { opacity: 0.35; cursor: default; }
</style>
