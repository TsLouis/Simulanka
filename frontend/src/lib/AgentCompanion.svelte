<script lang="ts">
  import './agent-canvas-projection'
  import type { AgentSessionController } from './agent-session'
  import { hasAgentDragRef, readAgentDragRefs } from './agent-dnd'
  import {
    conversationProjectionFromEvents,
    setConversationProjection,
  } from './agent-projection'
  import SessionHistory from './SessionHistory.svelte'
  import SessionRecovery from './SessionRecovery.svelte'

  export let controller: AgentSessionController

  $: busy = $controller.busy
  $: readOnly = $controller.readOnly
  $: refs = $controller.pendingRefs
  $: preview = $controller.preview
  $: previewBusy = $controller.previewBusy
  $: previewError = $controller.previewError
  $: turnProjection = conversationProjectionFromEvents($controller.events)
  $: setConversationProjection(turnProjection)
  $: projectedRefCount = turnProjection.refs.length
  $: feedback = $controller.events.findLast(
    event => event.type === 'agent_text' || event.type === 'error',
  )
  // OpenCode streams one answer as several agent_text events. The projection
  // parser already aggregates the latest turn and strips sidecar protocol, so
  // use that human-readable text instead of showing only the final raw chunk.
  $: feedbackText = feedback?.type === 'error'
    ? (feedback.text ?? '')
    : (turnProjection.text ?? '')
  $: hasSuggestion = !busy && feedback?.type === 'agent_text' && Boolean(turnProjection.text || turnProjection.visuals.length)

  let discussionOpen = false
  let recoveryOpen = false
  let text = ''
  let open = false
  let lastRefCount = 0
  let dragActive = false
  let composerEl: HTMLTextAreaElement | null = null
  let pointerCollecting = false
  let pointerStartRefCount: number | null = null

  $: hasContext = refs.length > 0

  // Pointing is a collection gesture, not a focus gesture. While A is held the
  // user may click several nodes/ports/edges into one RefSet. We reveal the
  // Companion as refs arrive but wait until A is released before focusing the
  // composer, so the first pointed object never interrupts the next click.
  $: {
    const nextRefCount = refs.length
    if (nextRefCount > lastRefCount) open = true
    lastRefCount = nextRefCount
  }

  function isTypingTarget(target: EventTarget | null): boolean {
    const element = target as HTMLElement | null
    return element instanceof HTMLInputElement
      || element instanceof HTMLTextAreaElement
      || element?.isContentEditable === true
  }

  function onPointerKeydown(event: KeyboardEvent) {
    if (
      event.key.toLowerCase() !== 'a'
      || event.altKey
      || event.ctrlKey
      || event.metaKey
      || isTypingTarget(event.target)
    ) return
    if (pointerStartRefCount === null) pointerStartRefCount = refs.length
    pointerCollecting = true
  }

  function onPointerKeyup(event: KeyboardEvent) {
    if (event.key.toLowerCase() !== 'a' || pointerStartRefCount === null) return
    const addedAny = refs.length > pointerStartRefCount
    pointerStartRefCount = null
    pointerCollecting = false
    if (!addedAny) return
    open = true
    queueMicrotask(() => composerEl?.focus())
  }

  function onPointerBlur() {
    pointerStartRefCount = null
    pointerCollecting = false
  }

  function close() {
    open = false
    discussionOpen = false
  }

  function openRecovery() {
    recoveryOpen = true
    void controller.openRecovery()
  }

  function send() {
    if (!text.trim() || busy || readOnly) return
    const message = text
    text = ''
    void controller.sendMessage(message)
    queueMicrotask(() => composerEl?.focus())
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      send()
    }
    if (e.key === 'Escape') close()
  }

  function onDragEnter(event: DragEvent) {
    if (!hasAgentDragRef(event)) return
    event.preventDefault()
    dragActive = true
  }

  function onDragOver(event: DragEvent) {
    if (!hasAgentDragRef(event)) return
    event.preventDefault()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
    dragActive = true
  }

  function onDragLeave(event: DragEvent) {
    const current = event.currentTarget as HTMLElement | null
    const next = event.relatedTarget as Node | null
    if (current && next && current.contains(next)) return
    dragActive = false
  }

  function onDrop(event: DragEvent) {
    const droppedRefs = readAgentDragRefs(event)
    dragActive = false
    if (droppedRefs.length === 0) return
    event.preventDefault()
    for (const ref of droppedRefs) {
      controller.addPendingRef(
        { kind: ref.kind, ref_id: ref.ref_id },
        ref.label,
      )
    }
    open = true
    queueMicrotask(() => composerEl?.focus())
  }
</script>

<svelte:window
  on:keydown={onPointerKeydown}
  on:keyup={onPointerKeyup}
  on:blur={onPointerBlur}
/>

<div class="companion-shell" class:open>
  {#if open}
    <section class="companion-panel" class:with-discussion={discussionOpen} aria-label="Agent Companion">
      <header class="panel-head">
        <div class="agent-state">
          <strong>Agent <small>{$controller.providerId}</small></strong>
          <span>
            {busy
              ? projectedRefCount > 0
                ? `thinking on ${projectedRefCount} object${projectedRefCount === 1 ? '' : 's'}…`
                : 'thinking…'
              : readOnly
                ? 'read only'
                : pointerCollecting
                  ? `pointing · ${refs.length} object${refs.length === 1 ? '' : 's'}`
                  : hasContext
                    ? `looking at ${refs.length} object${refs.length === 1 ? '' : 's'}`
                    : projectedRefCount > 0 && hasSuggestion
                      ? `pointing at ${projectedRefCount} object${projectedRefCount === 1 ? '' : 's'}`
                      : hasSuggestion
                        ? 'idea ready'
                        : 'ready'}
          </span>
        </div>
        <div class="panel-actions">
          <button
            class:active={discussionOpen}
            aria-expanded={discussionOpen}
            on:click={() => (discussionOpen = !discussionOpen)}
            title="展开或收起完整讨论"
          >Discussion</button>
          <button
            on:click={() => controller.startNewSession()}
            disabled={busy || $controller.actionBusy}
            title="在当前图层开始新的讨论"
            aria-label="新建讨论"
          >＋</button>
          <button on:click={close} title="收起" aria-label="收起 Agent">×</button>
        </div>
      </header>

      {#if $controller.error}
        <div class="notice error" role="alert">{$controller.error}</div>
      {/if}

      {#if discussionOpen}
        <SessionHistory {controller} onRecovery={openRecovery} />
      {:else if feedbackText}
        <button
          class="feedback"
          class:error={feedback?.type === 'error'}
          on:click={() => (discussionOpen = true)}
          title="打开完整讨论"
        >
          <span class="feedback-mark">{feedback?.type === 'error' ? '!' : '✦'}</span>
          <span>{feedbackText.length > 180 ? `${feedbackText.slice(0, 180)}…` : feedbackText}</span>
        </button>
      {/if}

      {#if $controller.activeSession?.status === 'running'}
        <div class="session-status">
          {#if $controller.capabilities?.interrupt === true && $controller.interruptReady}
            <button
              on:click={() => void controller.stopActiveSession($controller.selectedTreeId!)}
              disabled={$controller.stopping || $controller.actionBusy}
              title="暂停当前轮；后续消息继续同一原生会话"
            >{$controller.stopping ? '暂停中…' : '暂停'}</button>
          {:else if $controller.capabilities?.interrupt === true}
            <span>等待会话准备完成</span>
          {:else if $controller.capabilities?.interrupt === false}
            <span>当前 Agent 不支持暂停</span>
          {/if}
        </div>
      {/if}

      {#if refs.length > 0}
        <div class="context-block">
          <div class="context-head">
            <span>Looking at · {refs.length}</span>
            <button class="text-button" on:click={() => void controller.previewPendingRefs()} disabled={previewBusy}>
              {previewBusy ? 'checking…' : 'check context'}
            </button>
          </div>
          <div class="chips">
            {#each refs as ref (`${ref.kind}:${ref.ref_id}`)}
              <span class="ref-chip" title={`${ref.kind}:${ref.ref_id}`}>
                <span class="kind">{ref.kind}</span>
                <span class="label">{ref.label}</span>
                <button
                  class:pinned={ref.pinned}
                  class="pin"
                  title={ref.pinned ? '发送后继续保留' : '固定到后续轮次'}
                  aria-label={ref.pinned ? `取消固定 ${ref.label}` : `固定 ${ref.label}`}
                  on:click={() => controller.togglePendingPin(ref)}
                >{ref.pinned ? '◆' : '◇'}</button>
                <button
                  class="remove"
                  title="移除"
                  aria-label={`移除 ${ref.label}`}
                  on:click={() => controller.removePendingRef(ref)}
                >×</button>
              </span>
            {/each}
          </div>
        </div>
      {/if}

      {#if previewError}
        <div class="notice error" role="alert">{previewError}</div>
      {:else if preview}
        <div class="context-preview">
          <div class="preview-summary">
            <span class="preview-state">
              {preview.delivery.action === 'send' ? 'Context ready' : 'Context already known'}
            </span>
            <span>{preview.sources.length} source{preview.sources.length === 1 ? '' : 's'}</span>
            {#if preview.omissions.length > 0}
              <span class="warning">{preview.omissions.length} omitted</span>
            {/if}
          </div>
          <details class="technical-preview">
            <summary>Technical details</summary>
            <div class="preview-meta"><code>{preview.delivery.reason}</code></div>
            <pre>{JSON.stringify(preview.payload, null, 2)}</pre>
          </details>
        </div>
      {/if}

      <div class="composer">
        <textarea
          bind:this={composerEl}
          rows="2"
          placeholder={readOnly ? 'This discussion is read only' : hasContext ? 'Ask about these objects…' : 'Ask anything…'}
          bind:value={text}
          on:keydown={onKeydown}
          disabled={busy || readOnly}
        ></textarea>
        <button class="send" on:click={send} disabled={busy || readOnly || !text.trim()} title="发送">
          {busy ? '…' : '↗'}
        </button>
      </div>
      <div class="privacy-note" title="视口、邻居和祖先不会因为你正在看它们而自动进入上下文">
        Hold <kbd>A</kbd>, click one or more graph objects, release <kbd>A</kbd>, then type · only explicit objects are shared.
      </div>
    </section>
  {/if}

  <button
    class="pet"
    class:busy
    class:drag-active={dragActive}
    class:pointer-collecting={pointerCollecting}
    class:has-context={hasContext}
    class:has-suggestion={hasSuggestion}
    class:has-projection={projectedRefCount > 0}
    class:active={open}
    data-agent-drop-target
    aria-label={open ? '收起 Agent' : '打开 Agent'}
    title={dragActive ? 'Drop to show these objects to the Agent' : pointerCollecting ? 'Keep clicking graph objects; release A when finished' : open ? '收起 Agent' : 'Agent · hold A + click graph objects to point them out'}
    on:dragenter={onDragEnter}
    on:dragover={onDragOver}
    on:dragleave={onDragLeave}
    on:drop={onDrop}
    on:click={() => { if (open) close(); else { open = true; queueMicrotask(() => composerEl?.focus()) } }}
  >
    <span class="pet-face" aria-hidden="true">
      <i></i><i></i>
      <b></b>
    </span>
    {#if refs.length > 0}
      <span class="badge">{refs.length}</span>
    {:else if projectedRefCount > 0}
      <span class="badge projection-badge">{projectedRefCount}</span>
    {/if}
    {#if hasSuggestion && !open}<span class="suggestion-dot" title="Agent 有新的想法"></span>{/if}
  </button>
</div>

{#if recoveryOpen}
  <SessionRecovery
    sessions={$controller.recovery.sessions}
    selectedSessionId={$controller.recovery.sessionId}
    events={$controller.recovery.events}
    loading={$controller.recovery.busy}
    error={$controller.recovery.error}
    onSelect={(sessionId) => void controller.openRecoverySession(sessionId)}
    onRefresh={() => void controller.openRecovery()}
    onClose={() => (recoveryOpen = false)}
  />
{/if}

<style>
  .companion-panel.with-discussion { width: min(680px, calc(100vw - 36px)); }
  .agent-state { min-width: 0; }
  .panel-head small { color: var(--muted); font-size: 10px; font-weight: normal; }

  .feedback {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    width: calc(100% - 20px);
    margin: 8px 10px 0;
    padding: 7px;
    max-height: 64px;
    overflow: auto;
    text-align: left;
    overflow-wrap: anywhere;
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--hairline-2);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
  }
  .feedback-mark { flex: 0 0 auto; color: var(--violet); font-family: var(--font-mono); }
  .feedback.error,
  .feedback.error .feedback-mark { color: var(--red); }

  .session-status { padding: 5px 10px; color: var(--muted); font-size: 10px; }
  .session-status button {
    border: 1px solid var(--hairline);
    background: var(--panel-2);
    color: var(--gold);
    cursor: pointer;
    font: inherit;
  }

  .companion-shell {
    position: absolute;
    right: 18px;
    bottom: 18px;
    z-index: 25;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
    pointer-events: none;
  }
  .companion-shell > * { pointer-events: auto; }

  .pet {
    position: relative;
    width: 46px;
    height: 46px;
    padding: 0;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28);
    transition: border-color 0.12s, transform 0.12s, box-shadow 0.12s;
  }
  .pet:hover,
  .pet.active,
  .pet.pointer-collecting,
  .pet.has-context,
  .pet.has-suggestion,
  .pet.has-projection { border-color: var(--violet); }
  .pet.pointer-collecting {
    box-shadow: 0 0 0 3px rgba(177, 138, 243, 0.1), 0 6px 20px rgba(0, 0, 0, 0.28);
  }
  .pet.drag-active {
    border-color: var(--violet);
    transform: scale(1.08);
    box-shadow: 0 0 0 4px rgba(177, 138, 243, 0.12), 0 8px 24px rgba(0, 0, 0, 0.34);
  }
  .pet.busy .pet-face { animation: pet-think 0.8s steps(2, end) infinite; }

  @keyframes pet-think { 50% { transform: translateY(-2px); } }

  .pet-face {
    position: absolute;
    inset: 10px 9px 9px;
    border: 2px solid var(--violet);
    image-rendering: pixelated;
  }
  .pet-face::before,
  .pet-face::after {
    content: '';
    position: absolute;
    top: -5px;
    width: 5px;
    height: 5px;
    background: var(--violet);
  }
  .pet-face::before { left: 2px; }
  .pet-face::after { right: 2px; }
  .pet-face i {
    position: absolute;
    top: 8px;
    width: 3px;
    height: 3px;
    background: var(--text);
  }
  .pet-face i:first-child { left: 5px; }
  .pet-face i:nth-child(2) { right: 5px; }
  .pet-face b {
    position: absolute;
    left: 50%;
    bottom: 5px;
    width: 7px;
    height: 2px;
    transform: translateX(-50%);
    background: var(--muted);
  }

  .badge,
  .suggestion-dot {
    position: absolute;
    box-sizing: border-box;
    border: 1px solid var(--canvas-bg);
    background: var(--violet);
  }
  .badge {
    right: -5px;
    top: -5px;
    min-width: 16px;
    height: 16px;
    padding: 0 3px;
    display: grid;
    place-items: center;
    border-radius: 4px;
    color: #08111f;
    font: 700 9px var(--font-mono);
  }
  .projection-badge { background: var(--panel-2); color: var(--violet); border-color: var(--violet); }
  .suggestion-dot {
    right: -3px;
    bottom: -3px;
    width: 9px;
    height: 9px;
  }

  .companion-panel {
    width: min(420px, calc(100vw - 36px));
    max-height: min(62vh, 520px);
    overflow: auto;
    box-sizing: border-box;
    padding: 10px;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: rgba(12, 23, 38, 0.97);
    box-shadow: 0 14px 38px rgba(0, 0, 0, 0.42);
    color: var(--text);
    font-size: 12px;
  }

  .panel-head,
  .context-head,
  .preview-summary,
  .preview-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .panel-head {
    padding-bottom: 8px;
    border-bottom: 1px solid var(--hairline-2);
  }
  .panel-head strong {
    color: var(--ivory);
    font: 600 13px var(--font-mono);
  }
  .panel-head span,
  .privacy-note,
  .preview-summary,
  .preview-meta {
    color: var(--muted);
    font-size: 10px;
  }
  .panel-head span { margin-left: 8px; }
  .panel-actions { display: flex; gap: 4px; }

  button {
    border: 1px solid var(--hairline);
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  button:hover:not(:disabled) { border-color: var(--violet); color: var(--ivory); }
  button:disabled { opacity: 0.45; cursor: default; }
  .panel-actions button,
  .ref-chip button { min-width: 24px; height: 24px; padding: 0 5px; }
  .panel-actions button.active { border-color: var(--violet); }

  .context-block { padding: 9px 0 4px; }
  .context-head {
    margin-bottom: 6px;
    color: var(--muted);
    font: 10px var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .text-button {
    padding: 2px 6px;
    border: 0;
    background: transparent;
    color: var(--blue);
  }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .ref-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    max-width: 100%;
    padding: 3px 3px 3px 7px;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: var(--panel-3);
  }
  .ref-chip .kind {
    color: var(--violet);
    font: 9px var(--font-mono);
    text-transform: uppercase;
  }
  .ref-chip .label {
    max-width: 210px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ref-chip .pin,
  .ref-chip .remove { border: 0; background: transparent; color: var(--muted); }
  .ref-chip .pin.pinned { color: var(--violet); }

  .notice,
  .context-preview {
    margin: 7px 0;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: var(--panel-3);
  }
  .notice { padding: 7px; }
  .notice.error { color: var(--red); }
  .context-preview { padding: 7px; }
  .preview-summary { justify-content: flex-start; flex-wrap: wrap; }
  .preview-state { color: var(--jade); }
  .preview-summary .warning { color: var(--amber); }
  .technical-preview { margin-top: 7px; color: var(--muted); }
  .technical-preview summary { cursor: pointer; font-size: 10px; }
  .preview-meta { padding: 6px 0; justify-content: flex-start; }
  .technical-preview pre {
    max-height: 150px;
    overflow: auto;
    margin: 0;
    padding: 7px;
    border: 1px solid var(--hairline-2);
    color: #a9b9cf;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: 10px/1.45 var(--font-mono);
  }

  .composer {
    display: flex;
    align-items: stretch;
    gap: 6px;
    margin-top: 8px;
  }
  textarea {
    flex: 1;
    min-width: 0;
    resize: none;
    box-sizing: border-box;
    padding: 8px 9px;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    outline: none;
    background: var(--panel-3);
    color: var(--text);
    font: 12px/1.45 var(--font-body);
  }
  textarea:focus { border-color: var(--violet); }
  .send { width: 38px; padding: 0; color: var(--violet); font-size: 18px; }
  .privacy-note {
    margin-top: 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .privacy-note kbd {
    padding: 0 3px;
    border: 1px solid var(--hairline);
    border-bottom-color: var(--muted);
    border-radius: 2px;
    background: var(--panel-3);
    color: var(--ivory);
    font: 9px var(--font-mono);
  }
</style>