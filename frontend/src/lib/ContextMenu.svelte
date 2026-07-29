<script lang="ts">
  import { onMount } from 'svelte'
  import { filterGroups, type NodeTemplate, type TemplateGroup } from './templates'
  import type { NodeDTO } from './types'

  // Viewport coordinates of the right-click; the menu clamps itself to stay
  // on screen.
  export let x: number
  export let y: number
  export let mode: 'add' | 'node'
  export let node: NodeDTO | null = null
  export let groups: TemplateGroup[] = []
  export let onClose: () => void
  export let onPick: (t: NodeTemplate) => void = () => {}
  export let onEnter: () => void = () => {}
  export let onRename: () => void = () => {}
  export let onSaveTemplate: () => void = () => {}
  export let onDelete: () => void = () => {}
  export let onDeleteTemplate: (name: string) => void = () => {}
  export let onAttach: () => void = () => {}

  // Canvas delete covers the model-sketch domain only (server policy) — the
  // menu doesn't offer what the kernel would refuse.
  $: deletable = node !== null && (node.type === 'module' || node.type === 'model')

  let query = ''
  let searchEl: HTMLInputElement | null = null
  let menuEl: HTMLDivElement

  $: filtered = filterGroups(groups, query)
  $: firstMatch = filtered[0]?.items[0] ?? null

  // Clamp inside the viewport (menu is max 420 tall / 260 wide).
  $: left = Math.min(x, window.innerWidth - 270)
  $: top = Math.min(y, window.innerHeight - 430)

  onMount(() => {
    searchEl?.focus()
  })

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'Enter' && mode === 'add' && firstMatch) {
      e.preventDefault()
      onPick(firstMatch)
    }
  }

  function onGlobalPointerDown(e: MouseEvent) {
    if (menuEl && !menuEl.contains(e.target as Node)) onClose()
  }
</script>

<!-- capture 相:LiteGraph 在画布 mousedown 里吃掉冒泡,常规监听收不到,
     菜单就收不起来——捕获相先于画布处理器,点画布任意处都能关。 -->
<svelte:window on:keydown={onKeydown} on:mousedown|capture={onGlobalPointerDown} />

<div class="menu" bind:this={menuEl} style="left: {left}px; top: {top}px;" role="menu">
  {#if mode === 'add'}
    <input
      class="search"
      placeholder="添加节点…"
      bind:value={query}
      bind:this={searchEl}
    />
    <div class="list">
      {#each filtered as g (g.category)}
        <div class="cat">{g.category}</div>
        {#each g.items as t (t.category + '/' + t.label)}
          <button class="row" on:click={() => onPick(t)}>
            <span class="label">{t.label}</span>
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
        <div class="empty">无匹配</div>
      {/if}
    </div>
  {:else if node}
    <div class="node-head">
      <span class="type-chip">{node.type}</span>
      <span class="node-name">{node.name}</span>
    </div>
    <button class="row action" on:click={onEnter}>
      进入子图 ⤢
      {#if node.child_count > 0}<span class="hint">{node.child_count} 项</span>{/if}
    </button>
    <button class="row action" on:click={onRename}>重命名 ✎</button>
    <button class="row action" on:click={onAttach}>附加上下文 ＋</button>
    <button class="row action" on:click={onSaveTemplate}>存为模板 ⧉</button>
    {#if deletable}
      <button class="row action danger" on:click={onDelete}>删除 ✕</button>
    {/if}
  {/if}
</div>

<style>
  /* 星图册: 夜漆浮层 + 金缘,与 header/inspector 同一调色板 */
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
  .search {
    background: var(--panel-3);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 5px;
    padding: 6px 9px;
    font: inherit;
    margin-bottom: 6px;
  }
  .search:focus {
    outline: none;
    border-color: var(--gold-dim);
    box-shadow: 0 0 0 2px rgba(217, 186, 125, 0.15);
  }
  .list {
    overflow-y: auto;
    max-height: 340px;
  }
  .cat {
    color: var(--gold-dim);
    font-size: 11px;
    letter-spacing: 0.08em;
    padding: 7px 8px 3px;
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
    padding: 5px 10px;
    border-radius: 5px;
    cursor: pointer;
    font: inherit;
  }
  .row:hover {
    background: var(--panel-2);
    color: var(--ivory);
  }
  .del {
    color: var(--muted);
    font-size: 11px;
    padding: 0 3px;
    border-radius: 3px;
  }
  .del:hover {
    color: var(--crimson);
  }
  .empty {
    color: var(--muted);
    padding: 12px;
    text-align: center;
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
    color: var(--gold);
    border: 1px solid var(--gold-dim);
    border-radius: 8px;
    font-size: 10px;
    padding: 1px 7px;
  }
  .node-name {
    color: var(--ivory);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .action {
    padding: 7px 10px;
  }
  .danger:hover {
    color: var(--crimson);
    background: rgba(224, 122, 104, 0.1);
  }
  .hint {
    color: var(--muted);
    font-size: 11px;
  }
</style>
