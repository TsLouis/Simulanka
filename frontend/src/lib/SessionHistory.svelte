<script lang="ts">
  import type { AgentSessionController } from './agent-session'
  import type { SessionEventDTO } from './api'
  import SessionTranscript from './SessionTranscript.svelte'

  export let controller: AgentSessionController
  export let onRecovery: () => void

  $: tree = $controller.trees.find(tree => tree.treeId === $controller.selectedTreeId)
  $: session = $controller.activeSession
  $: cacheLabel = cacheLabelForEvents($controller.events)

  function shortId(id: string): string {
    return id.length > 12 ? `…${id.slice(-10)}` : id
  }

  function cacheLabelForEvents(events: SessionEventDTO[]): string | null {
    for (let index = events.length - 1; index >= 0; index -= 1) {
      const usage = events[index].details?.usage
      if (usage && typeof usage === 'object' && !Array.isArray(usage)) {
        const cached = (usage as Record<string, unknown>).cached_input_tokens
        return `cache ${typeof cached === 'number' ? cached : '未报告'}`
      }
    }
    return events.some(event => event.type === 'status' && event.status === 'done')
      ? 'cache 未报告'
      : null
  }
</script>

<section class="session-history" aria-label="讨论与会话历史">
  <div class="session-picker">
    <label>
      讨论
      <select
        value={$controller.selectedTreeId ?? ''}
        disabled={$controller.actionBusy}
        on:change={(event) => controller.selectTree(event.currentTarget.value)}
      >
        <option value="" disabled>新讨论</option>
        {#each $controller.trees as item, index (item.treeId)}
          <option value={item.treeId}>讨论 {index + 1} · {shortId(item.treeId)}{item.busy ? ' · running' : ''}</option>
        {/each}
      </select>
    </label>
    <label>
      分支
      <select
        value={session?.session_id ?? ''}
        disabled={!tree || $controller.busy || $controller.actionBusy}
        on:change={(event) => void controller.openSession(event.currentTarget.value)}
      >
        <option value="" disabled>尚未创建</option>
        {#each tree?.sessions ?? [] as branch (branch.session_id)}
          <option value={branch.session_id}>
            {shortId(branch.session_id)} · {branch.parent_session_id ? 'fork' : 'root'} · {branch.provider_id} · {branch.status}
          </option>
        {/each}
      </select>
    </label>
  </div>

  <div class="session-actions">
    <span title={session?.session_id}>{session?.status ?? '首条消息后持久化'}</span>
    {#if cacheLabel}<span>{cacheLabel}</span>{/if}
    <button
      on:click={() => void controller.restoreSessions()}
      disabled={$controller.listBusy}
      title="刷新当前图层的会话列表"
    >{$controller.listBusy ? '加载中…' : '刷新'}</button>
    <button
      on:click={() => void controller.forkActiveSession(tree!.treeId)}
      disabled={!session || $controller.busy || $controller.actionBusy}
      title="从当前分支 fork"
    >fork</button>
    <button
      on:click={() => void controller.archiveActiveSession(tree!.treeId)}
      disabled={!session || $controller.busy || $controller.actionBusy || session.status === 'archived' || session.status === 'running'}
      title="非破坏归档当前分支"
    >归档</button>
    <button on:click={onRecovery} title="查看未分配或损坏的会话树">会话恢复区</button>
  </div>

  <SessionTranscript events={$controller.events} busy={$controller.busy} />
</section>

<style>
  .session-history {
    display: flex;
    flex-direction: column;
    height: min(40vh, 360px);
    min-height: 180px;
    margin-top: 8px;
    border: 1px solid var(--hairline-2);
    background: var(--panel-3);
  }
  .session-picker, .session-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    padding: 6px;
    border-bottom: 1px solid var(--hairline-2);
    font-size: 10px;
  }
  label {
    display: flex;
    align-items: center;
    flex: 1;
    min-width: 0;
    gap: 5px;
    color: var(--muted);
  }
  select {
    width: 100%;
    min-width: 0;
  }
  button, select {
    padding: 3px 5px;
    border: 1px solid var(--hairline);
    border-radius: 3px;
    background: var(--panel-2);
    color: var(--text);
    font: inherit;
  }
  button { cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--violet); }
  button:disabled, select:disabled { opacity: 0.45; }
  .session-actions span { color: var(--muted); }
  @media (max-width: 540px) {
    .session-picker { flex-direction: column; align-items: stretch; }
  }
</style>
