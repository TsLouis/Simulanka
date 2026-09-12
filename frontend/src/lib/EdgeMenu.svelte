<script lang="ts">
  import { writeAgentDragRef } from './agent-dnd'
  import type { AffordanceDTO, EdgeDTO } from './types'

  // The server still owns the exact verdict/write-authority contract. This
  // component deliberately translates that machinery into lightweight product
  // language: keep, dismiss, needs attention, and explicit Agent context.
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

  let menuEl: HTMLDivElement
  $: left = Math.min(x, window.innerWidth - 270)
  $: top = Math.min(y, window.innerHeight - 250)

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  function onGlobalPointerDown(e: MouseEvent) {
    if (menuEl && !menuEl.contains(e.target as Node)) onClose()
  }

  function dragEdgeToAgent(event: DragEvent) {
    if (attachAction?.enabled !== true) {
      event.preventDefault()
      return
    }
    writeAgentDragRef(event, {
      kind: 'edge',
      ref_id: edge.id,
      label: `edge · ${srcName} → ${dstName}`,
    })
  }
</script>

<svelte:window on:keydown={onKeydown} on:mousedown|capture={onGlobalPointerDown} />

<div class="menu" bind:this={menuEl} style="left: {left}px; top: {top}px;" role="menu">
  <div
    class="head"
    class:draggable={attachAction?.enabled === true}
    draggable={attachAction?.enabled === true}
    on:dragstart={dragEdgeToAgent}
    title={attachAction?.enabled ? 'Drag this edge to the Agent' : edge.id}
  >
    <span class="source source-{source}">{isDraft ? 'draft' : source}</span>
    <span class="ends" title={edge.id}>{srcName} → {dstName}</span>
    <span class="edge-type">{edge.type}</span>
  </div>

  {#if reviewLabel(verdict)}
    <div class="state">
      {reviewLabel(verdict)}{#if verdictBy}<span> · {verdictBy}</span>{/if}
    </div>
  {/if}

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

  {#if attachAction}
    <button
      class="row agent"
      class:disabled={!attachAction.enabled}
      disabled={!attachAction.enabled}
      title={attachAction.enabled ? 'Point this edge to the Agent' : attachAction.reason}
      on:click={onAttach}
    >✦ Ask Agent
      {#if !attachAction.enabled}<span class="reason">{attachAction.reason}</span>{/if}
    </button>
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

<style>
  .menu {
    position: fixed;
    z-index: 50;
    width: 270px;
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
    margin-bottom: 4px;
  }
  .head.draggable { cursor: grab; }
  .head.draggable:active { cursor: grabbing; }

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

  .state {
    padding: 3px 8px 5px;
    color: var(--muted);
    font: 9px var(--font-mono);
    text-transform: uppercase;
  }
  .state span { text-transform: none; }

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
  .row.agent { color: var(--violet); }
  .row.quiet { color: var(--muted); }

  .disabled,
  .disabled:hover {
    color: var(--muted);
    background: transparent;
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
