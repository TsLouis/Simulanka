<script lang="ts">
  export let crumbs: { id: string; name: string }[] = []
  export let canBack = false
  export let canForward = false
  export let status = 'idle'
  export let positionWarning: string | null = null
  export let onDismissPositionWarning: () => void = () => {}
  export let liveOk = false
  export let liveVersion = -1
  export let nodeCount = 0
  export let edgeCount = 0
  export let boundaryCount = 0
  export let onBack: () => void
  export let onForward: () => void
  export let onCrumb: (index: number) => void
  export let onReload: () => void

  $: loading = status === 'loading…'
  $: statusText = status === 'top-level' || status.startsWith('root=') ? 'Ready' : status
  $: connectionText = liveOk ? 'Live' : liveVersion < 0 ? 'Connecting' : 'Reconnecting'
</script>

<div class="topbar">
  <header>
    <strong class="brand"><span class="brand-mark" aria-hidden="true">✦</span>Simulanka</strong>
    <div class="nav-btns" role="group" aria-label="View history">
      <button type="button" on:click={onBack} disabled={!canBack} aria-label="Back" title="Back · Alt+←">‹</button>
      <button type="button" on:click={onForward} disabled={!canForward} aria-label="Forward" title="Forward · Alt+→">›</button>
    </div>
    <nav class="crumbs" aria-label="Graph location">
      <button
        type="button" class="crumb" on:click={() => onCrumb(-1)}
        class:active={crumbs.length === 0}
        aria-current={crumbs.length === 0 ? 'location' : undefined}
        title="Top-level project graph"
      >Project</button>
      {#each crumbs as c, i (c.id)}
        <span class="sep" aria-hidden="true">/</span>
        <button
          type="button" class="crumb" on:click={() => onCrumb(i)}
          class:active={i === crumbs.length - 1}
          aria-current={i === crumbs.length - 1 ? 'location' : undefined}
          title={`${c.name} · ${c.id}`}
        >{c.name}</button>
      {/each}
    </nav>
    <div class="tools">
      <span class="connection" class:connected={liveOk} role="status" aria-live="polite"
        title={liveOk ? `Receiving graph updates · v${liveVersion}` : 'Realtime updates unavailable; automatic reconnect is active'}>
        <span class="live" aria-hidden="true"></span>{connectionText}
      </span>
      <button type="button" class="reload" on:click={onReload} disabled={loading}
        aria-label="Reload view" title="Reload the current graph view">
        <span class:loading aria-hidden="true">↻</span><span>Reload</span>
      </button>
    </div>
  </header>
  <div class="view-meta">
    <span class="primary-status" role="status" aria-live="polite" aria-atomic="true">{statusText}</span>
    <span class="counts" aria-label={`${nodeCount} nodes, ${edgeCount} edges, ${boundaryCount} boundary connections`}>
      <span><b>{nodeCount}</b> nodes</span><span><b>{edgeCount}</b> edges</span>
      {#if boundaryCount > 0}<span><b>{boundaryCount}</b> boundary</span>{/if}
    </span>
  </div>
  {#if positionWarning}
    <div class="position-notice">
      <span class="notice-icon" aria-hidden="true">!</span>
      <div class="notice-copy">
        <p role="status">Layout not saved. Graph edits are kept; local positions remain in this tab.</p>
        <details><summary>Details</summary><p class="error-detail">{positionWarning}</p></details>
      </div>
      <button type="button" class="dismiss" on:click={onDismissPositionWarning}
        aria-label="Dismiss layout warning" title="Dismiss this notice; does not retry saving">×</button>
    </div>
  {/if}
</div>

<style>
  .topbar { flex: none; min-width: 0; background: var(--panel-3); border-bottom: 1px solid var(--hairline-2); }
  header { display: flex; align-items: center; gap: 14px; min-height: 56px; padding: 8px 18px; box-sizing: border-box; }
  .brand { display: flex; align-items: center; gap: 9px; flex: none; font: 700 15px var(--font-display); letter-spacing: .04em; color: var(--ivory); }
  .brand-mark { display: grid; place-items: center; width: 29px; height: 29px; border: 1px solid var(--hairline); border-radius: 8px; background: var(--panel-2); color: var(--blue); font-size: 19px; }
  button { display: inline-flex; align-items: center; justify-content: center; min-height: 34px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--text); cursor: pointer; font: inherit; font-size: 12px; transition: background .15s, border-color .15s, color .15s; }
  button:hover:not(:disabled) { background: var(--panel-2); border-color: var(--hairline); color: var(--ivory); }
  button:focus-visible, summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
  button:disabled { opacity: .4; cursor: not-allowed; }
  .nav-btns { display: flex; flex: none; gap: 2px; padding-left: 12px; border-left: 1px solid var(--hairline-2); }
  .nav-btns button { width: 34px; font-size: 22px; }
  .crumbs { display: flex; align-items: center; flex: 1; min-width: 0; gap: 3px; overflow-x: auto; padding: 3px; }
  .crumb { flex: none; max-width: 240px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 7px 9px; }
  .crumb.active { color: var(--ivory); background: var(--panel-2); }
  .sep { color: var(--muted); font-size: 11px; }
  .tools { display: flex; flex: none; align-items: center; gap: 14px; }
  .connection { display: inline-flex; align-items: center; gap: 7px; color: var(--gold); font-size: 11px; white-space: nowrap; }
  .connection.connected { color: var(--jade); }
  .live { width: 6px; height: 6px; flex: none; border-radius: 50%; background: currentColor; }
  .reload { gap: 7px; padding: 6px 10px; border-color: var(--hairline); background: var(--panel); }
  .reload > span:first-child { display: inline-block; font-size: 18px; line-height: 1; }
  .loading { animation: spin 1.2s linear infinite; }
  .view-meta { display: flex; align-items: baseline; gap: 16px; padding: 0 19px 8px; font: 11px var(--font-mono); color: var(--muted); }
  .primary-status { flex: 1; min-width: 0; overflow-wrap: anywhere; max-height: 72px; overflow-y: auto; color: var(--text); }
  .counts { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 12px; }
  .counts b { font-weight: 500; color: var(--text); }
  .position-notice { display: flex; align-items: flex-start; gap: 10px; margin: 2px 14px 10px; padding: 10px 12px; border: 1px solid var(--gold-dim); border-radius: 7px; background: var(--gold-glow); font-size: 12px; }
  .notice-icon { flex: none; display: grid; place-items: center; width: 18px; height: 18px; border: 1px solid var(--gold-dim); border-radius: 50%; color: var(--gold-bright); font-weight: 700; }
  .notice-copy { flex: 1; min-width: 0; }
  .notice-copy p { margin: 0; line-height: 1.6; overflow-wrap: anywhere; }
  summary { width: fit-content; margin-top: 4px; color: var(--gold-bright); cursor: pointer; }
  .notice-copy .error-detail { margin-top: 6px; max-height: 120px; overflow-y: auto; color: var(--text); }
  .dismiss { flex: none; margin-top: -4px; min-width: 34px; font-size: 21px; color: var(--gold-bright); }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (max-width: 760px) {
    header { flex-wrap: wrap; gap: 8px; padding: 9px 12px 5px; }
    .brand { font-size: 14px; }
    .nav-btns { margin-left: auto; padding-left: 0; border-left: 0; }
    .tools { gap: 9px; }
    .crumbs { order: 4; flex-basis: 100%; }
    .crumb { max-width: 210px; }
    .view-meta { padding: 0 15px 8px; gap: 10px; }
    .counts { gap: 7px; }
    .position-notice { margin: 2px 10px 9px; padding: 9px; }
  }
  @media (max-width: 440px) {
    .brand { gap: 6px; font-size: 12px; letter-spacing: 0; }
    .brand-mark { width: 25px; height: 25px; }
    .nav-btns button { width: 30px; }
    .reload { padding: 6px 8px; }
    .reload > span:last-child { display: none; }
    .connection { font-size: 10px; gap: 5px; }
  }
  @media (prefers-reduced-motion: reduce) {
    button { transition: none; }
    .loading { animation: none; }
  }
</style>
