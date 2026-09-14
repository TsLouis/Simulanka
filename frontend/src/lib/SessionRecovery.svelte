<script lang="ts">
  import type { SessionDTO, SessionEventDTO } from './api'
  import SessionTranscript from './SessionTranscript.svelte'

  export let sessions: SessionDTO[] = []
  export let selectedSessionId: string | null = null
  export let events: SessionEventDTO[] = []
  export let loading = false
  export let error: string | null = null
  export let onSelect: (sessionId: string) => void = () => {}
  export let onRefresh: () => void = () => {}
  export let onClose: () => void = () => {}

  function shortId(value: string): string {
    return value.length > 14 ? `…${value.slice(-12)}` : value
  }
</script>

<aside class="recovery" aria-label="未分配会话恢复区">
  <header>
    <div>
      <strong>会话恢复区</strong>
      <small>旧 scope、已删除 scope 与损坏父链不会混入任何图层</small>
    </div>
    <button on:click={onRefresh} disabled={loading} title="刷新恢复区">↻</button>
    <button on:click={onClose} title="关闭恢复区">✕</button>
  </header>

  {#if error}
    <div class="error" role="alert">{error}</div>
  {/if}

  <div class="body">
    <nav aria-label="待恢复会话">
      {#if sessions.length === 0}
        <p>{loading ? '正在扫描…' : '没有待恢复会话'}</p>
      {:else}
        {#each sessions as session (session.session_id)}
          <button
            class:selected={selectedSessionId === session.session_id}
            on:click={() => onSelect(session.session_id)}
          >
            <code>{shortId(session.session_id)}</code>
            <span>tree {shortId(session.tree_id)}</span>
            <i>{session.scope_status} · {session.status}</i>
          </button>
        {/each}
      {/if}
    </nav>

    <section class="history" aria-live="polite">
      {#if selectedSessionId === null}
        <p>选择一个分支查看只读转录。</p>
      {:else if events.length === 0 && loading}
        <p>正在读取历史…</p>
      {:else}
        <SessionTranscript {events} emptyMessage="该分支没有可显示事件。" />
      {/if}
    </section>
  </div>
</aside>

<style>
  .recovery {
    position: absolute;
    inset: 18px 18px 76px auto;
    z-index: 55;
    width: min(720px, calc(100% - 36px));
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--gold-dim);
    border-radius: 10px;
    background: #111b30;
    box-shadow: 0 18px 52px rgba(0, 0, 0, 0.7);
    color: var(--text);
  }
  header {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--hairline);
    background: var(--panel-2);
  }
  header div {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  header strong {
    color: var(--gold-bright);
  }
  header small,
  nav p,
  .history p {
    color: var(--muted);
  }
  button {
    border: 1px solid var(--hairline);
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    cursor: pointer;
  }
  .body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(220px, 0.8fr) minmax(280px, 1.2fr);
  }
  nav,
  .history {
    min-height: 0;
    overflow: auto;
    padding: 9px;
  }
  nav {
    border-right: 1px solid var(--hairline);
  }
  nav button {
    width: 100%;
    display: grid;
    gap: 3px;
    margin-bottom: 5px;
    padding: 7px;
    text-align: left;
  }
  nav button.selected {
    border-color: var(--gold);
    background: rgba(217, 186, 125, 0.08);
  }
  nav span,
  nav i {
    color: var(--muted);
    font-size: 10px;
    font-style: normal;
  }
  .history { display: flex; flex-direction: column; }
  .error {
    color: var(--red);
    padding: 7px 12px;
    border-bottom: 1px solid var(--hairline);
  }
  @media (max-width: 680px) {
    .body {
      grid-template-columns: 1fr;
    }
    nav {
      max-height: 35%;
      border-right: 0;
      border-bottom: 1px solid var(--hairline);
    }
  }
</style>
