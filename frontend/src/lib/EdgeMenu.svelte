<script lang="ts">
  // S7 就地裁决：点选一条 data_flow 边（LiteGraph 链接中心点）在原地弹出
  // 人侧动作。动作本身由宿主执行（写权矩阵的 user 行走 server 端点）——
  // 本组件只是锚定在选择处的菜单壳。
  import type { AffordanceDTO, EdgeDTO } from './types'

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
  $: verdictAction = edge.affordances.find(action => action.id === 'edge.verdict') ?? null
  $: acceptAction = edge.affordances.find(action => action.id === 'edge.accept') ?? null
  $: discussAction = edge.affordances.find(action => action.id === 'edge.discuss') ?? null
  $: attachAction = edge.affordances.find(action => action.id === 'context.attach') ?? null

  const disabledTitle = (action: AffordanceDTO): string =>
    action.enabled ? action.label : action.reason

  let menuEl: HTMLDivElement

  // 视口内钳位（菜单约 260 宽 / 240 高）。
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
</script>

<!-- capture 相：LiteGraph 在画布 mousedown 里吃掉冒泡（与 ContextMenu 同坑） -->
<svelte:window on:keydown={onKeydown} on:mousedown|capture={onGlobalPointerDown} />

<div class="menu" bind:this={menuEl} style="left: {left}px; top: {top}px;" role="menu">
  <div class="head">
    <span class="chip src-{str('source') ?? 'user'}">{str('source') ?? '?'}</span>
    <span class="ends" title={edge.id}>{srcName} → {dstName}</span>
  </div>
  {#if verdictAction}
    {#if verdict}
      <div class="state">
        裁决: <b class="v-{verdict}">{verdict}</b>{#if verdictBy}&nbsp;by {verdictBy}{/if}
      </div>
    {/if}

    {#if verdictAction.enabled}
      <button class="row good" on:click={() => onVerdict('correct')}>✓ 裁决：正确</button>
      <button class="row bad" on:click={() => onVerdict('wrong')}>✗ 裁决：错误</button>
      <button class="row" on:click={() => onVerdict('disputed')}>⚖ 裁决：存疑</button>
    {:else}
      <button class="row disabled" disabled title={disabledTitle(verdictAction)}>
        {verdictAction.label}<span class="reason">{verdictAction.reason}</span>
      </button>
    {/if}
  {/if}
  {#if acceptAction}
    <button
      class="row good"
      class:disabled={!acceptAction.enabled}
      disabled={!acceptAction.enabled}
      title={disabledTitle(acceptAction)}
      on:click={onAccept}
    >✓ {acceptAction.label}
      {#if !acceptAction.enabled}<span class="reason">{acceptAction.reason}</span>{/if}
    </button>
  {/if}
  {#if discussAction}
    <button
      class="row"
      class:disabled={!discussAction.enabled}
      disabled={!discussAction.enabled}
      title={disabledTitle(discussAction)}
      on:click={onToggleDiscuss}
    >⇄ {inDiscuss ? '移出讨论' : '拉入讨论'}
      {#if !discussAction.enabled}<span class="reason">{discussAction.reason}</span>{/if}
    </button>
  {/if}
  {#if attachAction}
    <button
      class="row"
      class:disabled={!attachAction.enabled}
      disabled={!attachAction.enabled}
      title={disabledTitle(attachAction)}
      on:click={onAttach}
    >{attachAction.label} ＋
      {#if !attachAction.enabled}<span class="reason">{attachAction.reason}</span>{/if}
    </button>
  {/if}
</div>

<style>
  /* 星图册: 夜漆浮层 + 金缘，与 ContextMenu 同一调色板 */
  .menu {
    position: fixed;
    z-index: 50;
    width: 260px;
    background: linear-gradient(180deg, #1a2642 0%, #141e36 100%);
    border: 1px solid var(--hairline);
    border-radius: 8px;
    box-shadow:
      0 6px 24px rgba(0, 0, 0, 0.5),
      0 0 0 1px rgba(217, 186, 125, 0.08);
    padding: 6px;
    font-size: 13px;
    display: flex;
    flex-direction: column;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 8px 8px;
    border-bottom: 1px solid var(--hairline);
    margin-bottom: 5px;
  }
  .chip {
    border-radius: 8px;
    font-size: 10px;
    padding: 1px 7px;
    border: 1px solid currentColor;
    background: var(--panel-3);
  }
  .src-user {
    color: var(--amber);
  }
  .src-agent {
    color: var(--violet);
  }
  .src-trace {
    color: var(--star);
  }
  .ends {
    color: var(--ivory);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .state {
    color: var(--muted);
    font-size: 11px;
    padding: 2px 8px 6px;
  }
  .v-correct {
    color: var(--jade);
  }
  .v-wrong,
  .v-disputed {
    color: var(--crimson);
  }
  .v-uncertain {
    color: var(--gold);
  }
  .row {
    display: flex;
    align-items: center;
    width: 100%;
    background: transparent;
    border: none;
    color: var(--text);
    text-align: left;
    padding: 7px 10px;
    border-radius: 5px;
    cursor: pointer;
    font: inherit;
  }
  .row:hover {
    background: var(--panel-2);
    color: var(--ivory);
  }
  .good:hover {
    color: var(--jade);
    background: rgba(126, 207, 165, 0.1);
  }
  .bad:hover {
    color: var(--crimson);
    background: rgba(224, 122, 104, 0.1);
  }
  .disabled,
  .disabled:hover {
    color: var(--muted);
    background: transparent;
    cursor: not-allowed;
  }
  .reason {
    margin-left: auto;
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 10px;
  }
</style>
