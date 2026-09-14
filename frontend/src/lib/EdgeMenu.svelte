<script lang="ts">
  import type { AffordanceDTO, EdgeDTO } from './types'

  // Object-level interaction stays small and consistent: Ask talks to the Agent,
  // Inspect reveals the edge itself. Edge-specific write/review actions remain
  // below and continue to map directly to server affordances.
  export let x: number
  export let y: number
  export let edge: EdgeDTO
  export let srcName: string
  export let dstName: string
  export let onClose: () => void
  export let onVerdict: (verdict: 'correct' | 'wrong' | 'disputed') => void
  export let onAccept: () => void
  export let onToggleDiscuss: () => void
  export let onAttach: () => void = () => {}

  const str = (key: string): string | null =>
    typeof edge.attrs[key] === 'string' ? (edge.attrs[key] as string) : null

  $: inDiscuss = edge.attrs.discuss === true
  $: verdict = str('verdict')
  $: verdictBy = str('verdict_by')
  $: source = str('source') ?? 'user'
  // Provenance and lifecycle are separate. An accepted edge may still have
  // source=agent; only status=proposed is a Draft in the product surface.
  $: isDraft = str('status') === 'proposed'
  $: verdictAction = edge.affordances.find(action => action.id === 'edge.verdict') ?? null
  $: acceptAction = edge.affordances.find(action => action.id === 'edge.accept') ?? null
  $: canAccept = acceptAction?.enabled === true
  $: discussAction = edge.affordances.find(action => action.id === 'edge.discuss') ?? null
  $: attachAction = edge.affordances.find(action => action.id === 'context.attach') ?? null

  const disabledTitle = (action: AffordanceDTO): string =>
    action.enabled ? action.label : action.reason

  const reviewLabel = (value: string | null): string | null => {
    if (value === 'correct') return 'kept'
    if (value === 'wrong') return 'dismissed'
    if (value === 'disputed' || value === 'uncertain') return 'needs attention'
    return null
  }

  function formatVal(value: unknown): string {
    if (typeof value === 'string') return value
    if (value === null || value === undefined) return String(value)
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value, null, 2)
      } catch {
        return String(value)
      }
    }
    return String(value)
  }

  let menuEl: HTMLDivElement
  let inspecting = false
  $: left = Math.min(x, window.innerWidth - 292)
  $: top = Math.min(y, window.innerHeight - (inspecting ? 430 : 300))

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  function onGlobalPointerDown(e: MouseEvent) {
    if (menuEl && !menuEl.contains(e.target as Node)) onClose()
  }
</script>

<svelte:window on:keydown={onKeydown} on:mousedown|capture={onGlobalPointerDown} />

<div class="menu" bind:this={menuEl} style="left: {left}px; top: {top}px;" role="menu">
  <div class="head" title={edge.id}>
    <span class="source source-{source}">{isDraft ? 'draft' : source}</span>
    <span class="ends" title={edge.id}>{srcName} → {dstName}</span>
    <span class="edge-type">{edge.type}</span>
  </div>

  <div class="object-actions" aria-label="Edge actions">
    {#if attachAction}
      <button
        class="object-action ask"
        class:disabled={!attachAction.enabled}
        disabled={!attachAction.enabled}
        title={attachAction.enabled ? 'Ask the Agent about this edge' : attachAction.reason}
        on:click={onAttach}
      >✦ Ask</button>
    {/if}
    <button
      class="object-action"
      class:active={inspecting}
      aria-expanded={inspecting}
      title="Inspect this edge"
      on:click={() => (inspecting = !inspecting)}
    >Inspect</button>
  </div>

  {#if inspecting}
    <section class="inspect-panel" aria-label="Edge inspector">
      <dl>
        <dt>id</dt><dd><code>{edge.id}</code></dd>
        <dt>type</dt><dd>{edge.type}</dd>
        <dt>source</dt><dd>{source}</dd>
        <dt>from</dt><dd>{srcName}<small>{edge.src}</small></dd>
        <dt>to</dt><dd>{dstName}<small>{edge.dst}</small></dd>
        {#if edge.src_port}<dt>src port</dt><dd><code>{edge.src_port}</code></dd>{/if}
        {#if edge.dst_port}<dt>dst port</dt><dd><code>{edge.dst_port}</code></dd>{/if}
        {#if str('status')}<dt>status</dt><dd>{str('status')}</dd>{/if}
        {#if verdict}<dt>verdict</dt><dd>{verdict}{verdictBy ? ` · ${verdictBy}` : ''}</dd>{/if}
      </dl>
      {#if Object.keys(edge.attrs).length > 0}
        <details class="attrs">
          <summary>Attributes · {Object.keys(edge.attrs).length}</summary>
          <pre>{formatVal(edge.attrs)}</pre>
        </details>
      {/if}
    </section>
  {/if}

  {#if reviewLabel(verdict)}
    <div class="state">
      {reviewLabel(verdict)}{#if verdictBy}<span> · {verdictBy}</span>{/if}
    </div>
  {/if}

  <div class="review-actions" aria-label="Edge review actions">
    {#if canAccept}
      <button
        class="row keep"
        title={acceptAction?.label ?? 'Keep suggestion'}
        on:click={onAccept}
      >✓ Keep suggestion</button>
    {/if}

    {#if verdictAction}
      {#if verdictAction.enabled}
        {#if !canAccept}
          <button class="row keep" on:click={() => onVerdict('correct')}>✓ Looks right</button>
        {/if}
        <button class="row dismiss" on:click={() => onVerdict('wrong')}>
          × {isDraft ? 'Dismiss suggestion' : 'Looks wrong'}
        </button>
        <button class="row" on:click={() => onVerdict('disputed')}>◇ Needs attention</button>
      {:else}
        <button class="row disabled" disabled title={disabledTitle(verdictAction)}>
          Review unavailable<span class="reason">{verdictAction.reason}</span>
        </button>
      {/if}
    {/if}

    {#if discussAction}
      <button
        class="row quiet"
        class:disabled={!discussAction.enabled}
        disabled={!discussAction.enabled}
        title={disabledTitle(discussAction)}
        on:click={onToggleDiscuss}
      >{inDiscuss ? 'Remove attention mark' : 'Mark for attention'}
        {#if !discussAction.enabled}<span class="reason">{discussAction.reason}</span>{/if}
      </button>
    {/if}
  </div>
</div>

<style>
  .menu {
    position: fixed;
    z-index: 50;
    width: 292px;
    max-height: min(78vh, 540px);
    overflow: auto;
    box-sizing: border-box;
    padding: 5px;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: rgba(12, 23, 38, 0.98);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.38);
    font-size: 12px;
  }

  .head {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 7px;
    padding: 6px 7px 8px;
    border-bottom: 1px solid var(--hairline-2);
  }

  .source {
    flex: 0 0 auto;
    padding: 1px 5px;
    border: 1px solid currentColor;
    border-radius: 3px;
    color: var(--muted);
    font: 9px var(--font-mono);
    text-transform: uppercase;
  }
  .source-user { color: var(--amber); }
  .source-agent { color: var(--violet); }
  .source-trace { color: var(--blue); }

  .ends {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ivory);
  }
  .edge-type {
    color: var(--muted);
    font: 8px var(--font-mono);
    text-transform: uppercase;
  }

  .object-actions {
    display: flex;
    gap: 4px;
    padding: 6px 5px;
    border-bottom: 1px solid var(--hairline-2);
  }
  .object-action {
    min-height: 28px;
    padding: 3px 8px;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--text);
    cursor: pointer;
    font: 11px var(--font-body);
  }
  .object-action.ask { color: var(--violet); border-color: rgba(178, 140, 224, 0.45); }
  .object-action.active,
  .object-action:hover:not(:disabled) { border-color: var(--blue); color: var(--ivory); }

  .inspect-panel {
    margin: 5px;
    padding: 7px;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: var(--panel-3);
  }
  .inspect-panel dl {
    display: grid;
    grid-template-columns: 58px minmax(0, 1fr);
    gap: 4px 7px;
    margin: 0;
  }
  .inspect-panel dt {
    color: var(--muted);
    font: 9px var(--font-mono);
  }
  .inspect-panel dd {
    min-width: 0;
    margin: 0;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .inspect-panel dd small {
    display: block;
    margin-top: 1px;
    color: var(--muted);
    font: 8px var(--font-mono);
  }
  .inspect-panel code { color: var(--muted); font: 8px var(--font-mono); }
  .attrs { margin-top: 7px; }
  .attrs summary { cursor: pointer; color: var(--muted); font: 9px var(--font-mono); }
  .attrs pre {
    max-height: 130px;
    overflow: auto;
    margin: 6px 0 0;
    padding: 6px;
    border: 1px solid var(--hairline-2);
    background: rgba(8, 20, 33, 0.6);
    color: #a9b9cf;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: 8px/1.4 var(--font-mono);
  }

  .state {
    padding: 5px 8px 3px;
    color: var(--muted);
    font: 9px var(--font-mono);
    text-transform: uppercase;
  }
  .state span { text-transform: none; }

  .review-actions { padding-top: 3px; }
  .row {
    display: flex;
    align-items: center;
    width: 100%;
    min-height: 32px;
    padding: 6px 8px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
    font: inherit;
  }

  .row:hover:not(.disabled) {
    background: var(--panel-2);
    color: var(--ivory);
  }
  .row.keep:hover { color: var(--jade); }
  .row.dismiss:hover { color: var(--crimson); }
  .row.quiet { color: var(--muted); }

  .disabled,
  .disabled:hover,
  button:disabled {
    color: var(--muted);
    background: transparent;
    opacity: 0.58;
    cursor: not-allowed;
  }

  .reason {
    margin-left: auto;
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font-size: 9px;
  }
</style>