<script lang="ts">
  import { onMount } from 'svelte'
  import { filterGroups, type NodeTemplate, type TemplateGroup } from './templates'
  import type { AffordanceDTO, NodeDTO } from './types'

  // Viewport coordinates of the right-click / double-click summon point; the
  // menu clamps itself to stay on screen. Add mode follows the mature ComfyUI
  // node-search pattern: type to filter, arrows to select, Enter to create.
  export let x: number
  export let y: number
  export let mode: 'add' | 'node'
  export let nodes: NodeDTO[] = []
  export let affordances: AffordanceDTO[] = []
  export let groups: TemplateGroup[] = []
  export let onClose: () => void
  export let onPick: (t: NodeTemplate) => void = () => {}
  export let onAction: (action: AffordanceDTO) => void = () => {}
  export let onDeleteTemplate: (name: string) => void = () => {}

  $: node = nodes[0] ?? null

  const actionIcon = (id: string): string => ({
    'node.create': '＋',
    'node.enter': '⤢',
    'node.rename': '✎',
    'node.delete': '✕',
    'context.attach': '＋',
    'template.save': '⧉',
  })[id] ?? '›'

  let query = ''
  let searchEl: HTMLInputElement | null = null
  let menuEl: HTMLDivElement
  let activeIndex = 0

  $: filtered = filterGroups(groups, query)
  $: flatItems = filtered.flatMap(group => group.items)
  $: if (activeIndex >= flatItems.length) activeIndex = Math.max(0, flatItems.length - 1)

  // Clamp inside the viewport. The wider search surface gives template names,
  // profile and port structure enough room without becoming a side panel.
  $: left = Math.max(8, Math.min(x, window.innerWidth - 330))
  $: top = Math.max(8, Math.min(y, window.innerHeight - 470))

  onMount(() => {
    searchEl?.focus()
  })

  function moveSelection(delta: number) {
    if (flatItems.length === 0) return
    activeIndex = (activeIndex + delta + flatItems.length) % flatItems.length
    queueMicrotask(() => {
      menuEl
        ?.querySelector<HTMLElement>(`[data-add-index="${activeIndex}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    })
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
      return
    }
    if (mode !== 'add') return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveSelection(1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveSelection(-1)
    } else if (e.key === 'Enter' && flatItems[activeIndex]) {
      e.preventDefault()
      onPick(flatItems[activeIndex])
    }
  }

  function onQueryInput() {
    activeIndex = 0
  }

  function onGlobalPointerDown(e: MouseEvent) {
    if (menuEl && !menuEl.contains(e.target as Node)) onClose()
  }

  function portSummary(t: NodeTemplate): string {
    const inputs = t.ports.filter(port => port.direction === 'in').length
    const outputs = t.ports.length - inputs
    if (inputs === 0 && outputs === 0) return 'no ports'
    return `${inputs} in · ${outputs} out`
  }
</script>

<!-- capture 相:LiteGraph 在画布 mousedown 里吃掉冒泡,常规监听收不到,
     菜单就收不起来——捕获相先于画布处理器,点画布任意处都能关。 -->
<svelte:window on:keydown={onKeydown} on:mousedown|capture={onGlobalPointerDown} />

<div class="menu" bind:this={menuEl} style="left: {left}px; top: {top}px;" role="menu">
  {#if mode === 'add'}
    <div class="search-row">
      <span class="search-icon" aria-hidden="true">＋</span>
      <input
        class="search"
        placeholder="Search nodes…"
        bind:value={query}
        bind:this={searchEl}
        on:input={onQueryInput}
        autocomplete="off"
        spellcheck="false"
      />
    </div>
    <div class="hint">↑↓ select · Enter add · Esc close</div>
    <div class="list">
      {#each filtered as g (g.category)}
        <div class="cat">{g.category}</div>
        {#each g.items as t (t.category + '/' + t.label)}
          {@const index = flatItems.indexOf(t)}
          <button
            class="row add-row"
            class:active={index === activeIndex}
            data-add-index={index}
            on:mouseenter={() => (activeIndex = index)}
            on:click={() => onPick(t)}
          >
            <span class="node-result">
              <span class="label">{t.label}</span>
              <span class="meta">{t.type} · {portSummary(t)}</span>
            </span>
            {#if t.custom}
              <span
                class="del"
                role="button"
                tabindex="-1"
                title="删除模板"
                on:click|stopPropagation={() => onDeleteTemplate(t.label)}
                on:keydown|stopPropagation={() => {}}
              >✕</span>
            {/if}
          </button>
        {/each}
      {/each}
      {#if filtered.length === 0}
        <div class="empty">No matching nodes</div>
      {/if}
    </div>
  {:else if node}
    <div class="node-head">
      <span class="type-chip">{nodes.length > 1 ? `${nodes.length} 项` : node.type}</span>
      <span class="node-name">{nodes.length > 1 ? '多选' : node.name}</span>
    </div>
    {#each affordances as action (action.id)}
      <button
        class="row action"
        class:danger={action.id === 'node.delete'}
        class:disabled={!action.enabled}
        disabled={!action.enabled}
        title={action.enabled ? action.label : action.reason}
        on:click={() => onAction(action)}
      >
        <span>{action.label} {actionIcon(action.id)}</span>
        {#if !action.enabled}<span class="reason">{action.reason}</span>{/if}
      </button>
    {/each}
    {#if affordances.length === 0}<div class="empty">无可用动作</div>{/if}
  {/if}
</div>

<style>
  .menu {
    position: fixed;
    z-index: 50;
    width: 318px;
    max-height: 452px;
    overflow: hidden;
    background: rgba(10, 22, 36, 0.98);
    border: 1px solid var(--hairline);
    border-radius: 5px;
    box-shadow: 0 12px 34px rgba(0, 0, 0, 0.42);
    padding: 6px;
    font-size: 12px;
    display: flex;
    flex-direction: column;
  }

  .search-row {
    display: flex;
    align-items: center;
    gap: 6px;
    border: 1px solid var(--hairline);
    border-radius: 3px;
    background: var(--panel-3);
  }

  .search-icon {
    padding-left: 8px;
    color: var(--star);
    font: 700 13px var(--font-mono);
  }

  .search {
    min-width: 0;
    flex: 1;
    background: transparent;
    color: var(--ivory);
    border: 0;
    outline: none;
    padding: 8px 8px 8px 0;
    font: 12px var(--font-mono);
  }

  .search-row:focus-within { border-color: var(--star); }

  .hint {
    padding: 5px 7px 4px;
    color: var(--muted);
    font: 9px var(--font-mono);
  }

  .list {
    overflow-y: auto;
    max-height: 370px;
  }

  .cat {
    position: sticky;
    top: 0;
    z-index: 1;
    background: rgba(10, 22, 36, 0.98);
    color: var(--muted);
    font: 9px var(--font-mono);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 8px 7px 3px;
    user-select: none;
  }

  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    background: transparent;
    border: none;
    color: var(--text);
    text-align: left;
    padding: 6px 8px;
    border-radius: 3px;
    cursor: pointer;
    font: inherit;
  }

  .row:hover,
  .add-row.active {
    background: var(--panel-2);
    color: var(--ivory);
  }

  .node-result {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 2px;
  }

  .node-result .label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ivory);
  }

  .meta {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font: 9px var(--font-mono);
  }

  .del {
    color: var(--muted);
    font-size: 11px;
    padding: 3px;
    border-radius: 2px;
  }
  .del:hover { color: var(--crimson); }

  .empty {
    color: var(--muted);
    padding: 16px 10px;
    text-align: center;
    font: 10px var(--font-mono);
  }

  .node-head {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 8px 8px;
    border-bottom: 1px solid var(--hairline);
    margin-bottom: 5px;
  }

  .type-chip {
    background: var(--panel-3);
    color: var(--star);
    border: 1px solid var(--hairline);
    border-radius: 3px;
    font-size: 9px;
    padding: 2px 6px;
  }

  .node-name {
    color: var(--ivory);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .action { padding: 7px 8px; }
  .danger:hover {
    color: var(--crimson);
    background: rgba(238, 123, 115, 0.08);
  }
  .disabled,
  .disabled:hover {
    color: var(--muted);
    background: transparent;
    cursor: not-allowed;
  }
  .reason {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font-size: 9px;
  }
</style>