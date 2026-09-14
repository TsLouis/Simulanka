<script lang="ts">
  export let crumbs: { id: string; name: string }[] = []
  export let canBack = false
  export let canForward = false
  export let status = 'idle'
  export let liveOk = false
  export let liveVersion = -1
  export let nodeCount = 0
  export let edgeCount = 0
  export let boundaryCount = 0
  export let onBack: () => void
  export let onForward: () => void
  export let onCrumb: (index: number) => void
  export let onReload: () => void
</script>

<header>
  <strong class="brand"><span class="brand-mark">✦</span>Simulanka</strong>
  <span class="nav-btns">
    <button on:click={onBack} disabled={!canBack} title="后退(Alt+← / 鼠标侧键)">‹</button>
    <button on:click={onForward} disabled={!canForward} title="前进(Alt+→ / 鼠标侧键)">›</button>
  </span>
  <nav class="crumbs">
    <button class="crumb" on:click={() => onCrumb(-1)} class:active={crumbs.length === 0}>
      top
    </button>
    {#each crumbs as c, i}
      <span class="sep">/</span>
      <button
        class="crumb"
        on:click={() => onCrumb(i)}
        class:active={i === crumbs.length - 1}
        title={c.id}
      >
        {c.name}
      </button>
    {/each}
  </nav>
  <button on:click={onReload}>Reload</button>
  <span class="status">
    <span class="live" class:on={liveOk} title={liveOk ? `live · v${liveVersion}` : 'disconnected'}></span>
    {status} · {nodeCount}n / {edgeCount}e
    {#if boundaryCount > 0}/ {boundaryCount}↔{/if}
  </span>
</header>

<style>
  header {
    position: relative;
    display: flex;
    gap: 8px;
    align-items: center;
    min-height: 46px;
    box-sizing: border-box;
    padding: 7px 12px;
    background: #0a1624;
    border-bottom: 1px solid var(--hairline-2);
    font-size: 13px;
  }
  .brand {
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--ivory);
    display: flex;
    align-items: baseline;
    gap: 7px;
    user-select: none;
  }
  .brand-mark {
    font-size: 13px;
    color: var(--blue);
  }
  header button {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 3px;
    padding: 4px 12px;
    cursor: pointer;
    font-family: inherit;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  header button:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  .nav-btns {
    display: flex;
    gap: 4px;
  }
  .nav-btns button {
    padding: 2px 9px;
    font-size: 15px;
    line-height: 1;
  }
  .nav-btns button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .crumbs {
    min-width: 0;
    overflow-x: auto;
    white-space: nowrap;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .crumb {
    background: transparent;
    border: none;
    color: var(--muted);
    padding: 2px 7px;
    border-radius: 4px;
    cursor: pointer;
    font: inherit;
    transition:
      color 0.15s,
      background 0.15s;
  }
  .crumb:hover {
    color: var(--ivory);
    background: var(--panel-2);
  }
  .crumb.active {
    color: var(--gold-bright);
    font-weight: 500;
  }
  .sep {
    color: var(--gold-dim);
    font-size: 11px;
  }
  .status {
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    margin-left: auto;
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .live {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3a4763;
    transition: background 0.2s;
  }
  .live.on {
    background: var(--jade);
    box-shadow: 0 0 6px rgba(126, 207, 165, 0.8);
  }
</style>
