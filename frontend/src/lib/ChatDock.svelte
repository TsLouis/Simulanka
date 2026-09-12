<script lang="ts">
  import type { ContextPreviewDTO, ContextRefDTO } from './api'

  // Frontend v2: the agent is a canvas companion, not a permanent chat bar.
  // Context remains explicit: only refs supplied by the user enter the bundle.
  export let contextLabel: string
  export let busy = false
  export let readOnly = false
  export let panelOpen = false
  export let refs: Array<
    ContextRefDTO & { label: string; pinned: boolean }
  > = []
  export let preview: ContextPreviewDTO | null = null
  export let previewBusy = false
  export let previewError: string | null = null
  export let onSend: (text: string) => void
  export let onTogglePanel: () => void
  export let onRemoveRef: (ref: ContextRefDTO) => void = () => {}
  export let onTogglePin: (ref: ContextRefDTO) => void = () => {}
  export let onPreview: () => void = () => {}

  let text = ''
  let open = false
  let lastRefCount = 0

  $: hasContext = refs.length > 0

  // "Ask" and explicit attach should feel like handing an object to the Agent,
  // not like silently incrementing a badge. A newly attached ref therefore
  // opens the small composer, while removals never force UI state.
  $: {
    const nextRefCount = refs.length
    if (nextRefCount > lastRefCount) open = true
    lastRefCount = nextRefCount
  }

  function send() {
    if (!text.trim() || busy || readOnly) return
    const message = text
    text = ''
    onSend(message)
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      send()
    }
    if (e.key === 'Escape') {
      open = false
    }
  }
</script>

<div class="companion-shell" class:open>
  {#if open}
    <section class="companion-panel" aria-label="Agent Companion">
      <header class="panel-head">
        <div>
          <strong>Agent</strong>
          <span>{busy ? 'thinking…' : readOnly ? 'read only' : hasContext ? `looking at ${refs.length} object${refs.length === 1 ? '' : 's'}` : 'ready'}</span>
        </div>
        <div class="panel-actions">
          <button
            class:active={panelOpen}
            on:click={onTogglePanel}
            title="在当前图层创建新的讨论"
          >＋</button>
          <button on:click={() => (open = false)} title="收起">×</button>
        </div>
      </header>

      {#if refs.length > 0}
        <div class="context-block">
          <div class="context-head">
            <span>Context · {refs.length}</span>
            <button class="text-button" on:click={onPreview} disabled={previewBusy}>
              {previewBusy ? 'checking…' : 'preview'}
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
                  on:click={() => onTogglePin(ref)}
                >{ref.pinned ? '◆' : '◇'}</button>
                <button
                  class="remove"
                  title="移除"
                  aria-label={`移除 ${ref.label}`}
                  on:click={() => onRemoveRef(ref)}
                >×</button>
              </span>
            {/each}
          </div>
        </div>
      {/if}

      {#if previewError}
        <div class="preview error" role="alert">{previewError}</div>
      {:else if preview}
        <details class="preview">
          <summary>
            {preview.delivery.action === 'send' ? 'What the agent will see' : 'Context already known'}
          </summary>
          <div class="preview-meta">
            <code>{preview.delivery.reason}</code>
            <span>{preview.sources.length} sources · {preview.omissions.length} omitted</span>
          </div>
          <pre>{JSON.stringify(preview.payload, null, 2)}</pre>
        </details>
      {/if}

      <div class="composer">
        <textarea
          rows="2"
          placeholder={readOnly ? '该讨论只读；新建或 fork 后继续' : hasContext ? 'Ask about these objects…' : 'Ask anything…'}
          bind:value={text}
          on:keydown={onKeydown}
          disabled={busy || readOnly}
        ></textarea>
        <button class="send" on:click={send} disabled={busy || readOnly || !text.trim()} title="发送">
          {busy ? '…' : '↗'}
        </button>
      </div>
      <div class="context-label" title="只有显式附加的对象会进入上下文">
        {contextLabel}
      </div>
    </section>
  {/if}

  <button
    class="pet"
    class:busy
    class:has-context={hasContext}
    class:active={open}
    aria-label={open ? '收起 Agent' : '打开 Agent'}
    title={open ? '收起 Agent' : 'Agent · 只看你明确指给它的对象'}
    on:click={() => (open = !open)}
  >
    <span class="pet-face" aria-hidden="true">
      <i></i><i></i>
      <b></b>
    </span>
    {#if refs.length > 0}<span class="badge">{refs.length}</span>{/if}
  </button>
</div>

<style>
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

  .companion-shell > * {
    pointer-events: auto;
  }

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
  }

  .pet:hover,
  .pet.active,
  .pet.has-context {
    border-color: var(--violet);
  }

  .pet.busy .pet-face {
    animation: pet-think 0.8s steps(2, end) infinite;
  }

  @keyframes pet-think {
    50% { transform: translateY(-2px); }
  }

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

  .badge {
    position: absolute;
    right: -5px;
    top: -5px;
    min-width: 16px;
    height: 16px;
    padding: 0 3px;
    box-sizing: border-box;
    display: grid;
    place-items: center;
    border: 1px solid var(--sky);
    border-radius: 4px;
    background: var(--violet);
    color: #08111f;
    font: 700 9px var(--font-mono);
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
  .context-label,
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

  button:hover:not(:disabled) {
    border-color: var(--violet);
    color: var(--ivory);
  }

  button:disabled {
    opacity: 0.45;
    cursor: default;
  }

  .panel-actions button,
  .ref-chip button {
    min-width: 24px;
    height: 24px;
    padding: 0 5px;
  }

  .panel-actions button.active {
    border-color: var(--violet);
  }

  .context-block {
    padding: 9px 0 4px;
  }

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
    color: var(--star);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }

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
  .ref-chip .remove {
    border: 0;
    background: transparent;
    color: var(--muted);
  }

  .ref-chip .pin.pinned { color: var(--violet); }

  .preview {
    margin: 6px 0;
    border: 1px solid var(--hairline-2);
    border-radius: 4px;
    background: var(--panel-3);
  }

  .preview.error {
    padding: 7px;
    color: var(--red);
  }

  .preview summary {
    padding: 7px;
    cursor: pointer;
    color: var(--text);
  }

  .preview-meta { padding: 0 7px 6px; }

  .preview pre {
    max-height: 180px;
    overflow: auto;
    margin: 0;
    padding: 7px;
    border-top: 1px solid var(--hairline-2);
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

  .send {
    width: 38px;
    padding: 0;
    color: var(--violet);
    font-size: 18px;
  }

  .context-label {
    margin-top: 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
