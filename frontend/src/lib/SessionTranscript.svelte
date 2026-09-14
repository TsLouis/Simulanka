<script lang="ts">
  import { afterUpdate } from 'svelte'
  import type { SessionEventDTO } from './api'
  import { stripProjectionBlocks } from './agent-projection'

  // Mounted only when the user requests full discussion/history. The original
  // normalized events retain tool payloads, context audit details and usage.
  export let events: SessionEventDTO[] = []
  export let busy = false
  export let emptyMessage = '还没有消息。可在下方输入；所在层级不会自动加入上下文。'

  function formatDetail(value: unknown): string {
    if (typeof value === 'string') return value
    if (value === undefined) return '(无)'
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }

  function visibleEventText(event: SessionEventDTO): string {
    const fallback = event.status ?? event.type
    if (!event.text) return fallback
    return event.type === 'agent_text'
      ? stripProjectionBlocks(event.text) || fallback
      : event.text
  }

  function shortSessionId(value: string): string {
    return value.length > 12 ? `…${value.slice(-10)}` : value
  }

  interface ContextReferenceView {
    key: string
    label: string
    title: string
  }

  function contextReferences(details: Record<string, unknown>): ContextReferenceView[] {
    const bundles = details.context_bundles
    if (!Array.isArray(bundles)) return []
    const result: ContextReferenceView[] = []
    const seen = new Set<string>()
    for (const bundle of bundles) {
      if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) continue
      const refs = (bundle as Record<string, unknown>).refs
      if (!Array.isArray(refs)) continue
      for (const ref of refs) {
        if (!ref || typeof ref !== 'object' || Array.isArray(ref)) continue
        const value = ref as Record<string, unknown>
        if (typeof value.kind !== 'string' || typeof value.ref_id !== 'string') continue
        const key = `${value.kind}:${value.ref_id}`
        if (seen.has(key)) continue
        seen.add(key)
        result.push({
          key,
          label: `${value.kind}:${shortSessionId(value.ref_id)}`,
          title: key,
        })
      }
    }
    return result
  }

  function detailSummary(details: Record<string, unknown>): string {
    const usage = details.usage
    if (usage && typeof usage === 'object' && !Array.isArray(usage)) {
      const cached = (usage as Record<string, unknown>).cached_input_tokens
      return `usage · cache ${typeof cached === 'number' ? cached : '未报告'}`
    }
    const bundles = details.context_bundles
    if (Array.isArray(bundles)) {
      const refs = contextReferences(details)
      return refs.length > 0
        ? `context · ${refs.length} refs`
        : `context · ${bundles.length} bundle`
    }
    return '事件详情'
  }

  // Follow the tail as messages stream in — but never via tick() inside a
  // reactive statement: Svelte 5's tick() is microtask + flushSync, and from
  // a legacy `$:` that re-enters the flush forever. afterUpdate runs once per
  // completed render, outside the flush loop.
  let scrollEl: HTMLDivElement | null = null
  let renderedBubbles = -1
  afterUpdate(() => {
    const count = events.length + (busy ? 1 : 0)
    if (scrollEl && count !== renderedBubbles) {
      renderedBubbles = count
      scrollEl.scrollTop = scrollEl.scrollHeight
    }
  })
</script>

<div class="transcript" bind:this={scrollEl} aria-label="会话记录">
  {#each events as event, i (i)}
    {@const role = event.type === 'user_msg' ? 'user' : event.type === 'status' ? 'system' : 'agent'}
    <div class="msg {role}">
      {#if event.type === 'tool_call' || event.type === 'tool_result'}
        <details class="tool-card">
          <summary>
            <span class="tool-icon">{event.type === 'tool_call' ? '⚙' : '✓'}</span>
            <strong>{event.tool_name ?? 'tool'}</strong>
            <span class="tool-status">{event.status ?? (event.type === 'tool_call' ? 'running' : 'done')}</span>
          </summary>
          {#if event.call_id}<code class="call-id">{event.call_id}</code>{/if}
          {#if event.type === 'tool_call'}
            <span class="detail-label">输入</span>
            <pre>{formatDetail(event.input)}</pre>
          {:else}
            <span class="detail-label">结果</span>
            <pre>{formatDetail(event.output)}</pre>
          {/if}
        </details>
      {:else if event.type === 'status'}
        <div class="status-line status-{event.status ?? 'event'}">{visibleEventText(event)}</div>
      {:else}
        <div class="bubble" class:error={event.type === 'error'}>{visibleEventText(event)}</div>
      {/if}
      {#if event.details && Object.keys(event.details).length > 0}
        {@const refs = contextReferences(event.details)}
        {#if refs.length > 0}
          <div class="context-refs" aria-label="本轮上下文引用">
            {#each refs as ref (ref.key)}
              <code title={ref.title}>{ref.label}</code>
            {/each}
          </div>
        {/if}
        <details class="event-details">
          <summary>{detailSummary(event.details)}</summary>
          <pre>{formatDetail(event.details)}</pre>
        </details>
      {/if}
    </div>
  {/each}
  {#if busy}
    <div class="msg agent"><div class="bubble thinking">正在思考…</div></div>
  {/if}
  {#if events.length === 0 && !busy}
    <div class="empty">{emptyMessage}</div>
  {/if}
</div>

<style>
  .transcript {
    flex: 1;
    min-height: 120px;
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .context-refs {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
    color: var(--muted);
    font-size: 10px;
  }
  .msg {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }
  .msg.user {
    align-items: flex-end;
  }
  .msg.system {
    align-items: stretch;
  }
  .bubble {
    max-width: 85%;
    padding: 6px 10px;
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--panel-2);
    color: var(--text);
  }
  .msg.user .bubble {
    background: rgba(217, 186, 125, 0.14);
    border: 1px solid rgba(217, 186, 125, 0.3);
    color: var(--ivory);
  }
  .bubble.error {
    border: 1px solid rgba(232, 106, 106, 0.45);
    color: #f6b0b0;
  }
  .status-line {
    align-self: center;
    padding: 3px 8px;
    color: var(--muted);
    font-size: 11px;
  }
  .status-line.status-done {
    color: var(--jade);
  }
  .status-line.status-failed {
    color: var(--crimson);
  }
  .tool-card {
    width: min(100%, 520px);
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: rgba(9, 17, 31, 0.72);
  }
  .tool-card summary {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 7px 9px;
    cursor: pointer;
    color: var(--text);
  }
  .tool-icon {
    color: var(--gold);
  }
  .tool-status {
    margin-left: auto;
    color: var(--muted);
    font-size: 10px;
    text-transform: uppercase;
  }
  .detail-label,
  .call-id {
    display: block;
    margin: 6px 9px 2px;
    color: var(--gold-dim);
    font-size: 10px;
  }
  .tool-card pre {
    max-height: 240px;
    margin: 4px 9px 9px;
    overflow: auto;
    padding: 7px;
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    font-size: 11px;
    white-space: pre-wrap;
  }
  .event-details {
    max-width: 85%;
    margin-top: 3px;
    color: var(--muted);
    font-size: 10px;
  }
  .event-details summary {
    cursor: pointer;
    color: var(--gold-dim);
  }
  .event-details pre {
    max-height: 180px;
    overflow: auto;
    margin: 3px 0 0;
    padding: 6px;
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    white-space: pre-wrap;
  }
  .thinking {
    color: var(--muted);
    letter-spacing: 2px;
  }
  .empty {
    color: var(--muted);
    text-align: center;
    padding: 18px 8px;
  }
</style>
