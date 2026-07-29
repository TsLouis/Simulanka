<script lang="ts">
  import type { ContextPreviewDTO, ContextRefDTO } from './api'

  // 底部常驻输入条只负责消息和显式上下文提示；画布选择不会被静默注入。
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
  }
</script>

<div class="dock-shell">
  {#if refs.length > 0}
    <div class="refs-bar" aria-label="本轮显式补充上下文">
      <div class="refs-head">
        <span>本轮上下文 · {refs.length}</span>
        <button class="preview-button" on:click={onPreview} disabled={previewBusy}>
          {previewBusy ? '编译中…' : '预览实际内容'}
        </button>
      </div>
      <div class="chips">
        {#each refs as ref (`${ref.kind}:${ref.ref_id}`)}
          <span class="ref-chip" title={`${ref.kind}:${ref.ref_id}`}>
            <b>{ref.kind}</b>
            <span>{ref.label}</span>
            <button
              class:pinned={ref.pinned}
              class="pin"
              title={ref.pinned ? '取消固定；发送成功后将移除' : '固定到后续轮次'}
              aria-label={ref.pinned ? `取消固定 ${ref.label}` : `固定 ${ref.label}`}
              on:click={() => onTogglePin(ref)}
            >{ref.pinned ? '●' : '○'}</button>
            <button
              class="remove"
              title="从本轮上下文移除"
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
    <section class="preview">
      <header>
        <strong>{preview.delivery.action === 'send' ? '本轮将发送' : '本轮将跳过'}</strong>
        <code>{preview.delivery.reason}</code>
        <span>{preview.sources.length} 来源 · {preview.omissions.length} 省略</span>
      </header>
      <details open>
        <summary>Canonical payload</summary>
        <pre>{JSON.stringify(preview.payload, null, 2)}</pre>
      </details>
      <details>
        <summary>Sources ({preview.sources.length})</summary>
        <pre>{JSON.stringify(preview.sources, null, 2)}</pre>
      </details>
      {#if preview.omissions.length > 0}
        <details>
          <summary>Omissions</summary>
          <pre>{JSON.stringify(preview.omissions, null, 2)}</pre>
        </details>
      {/if}
    </section>
  {/if}

  <div class="dock">
    <span class="context" title="只发送你显式附加的上下文">
      ◇ {contextLabel}
    </span>
    <input
      placeholder={readOnly ? '该会话只读；请新建或 fork 后继续' : '直接和 agent 对话…（Enter 发送）'}
      bind:value={text}
      on:keydown={onKeydown}
      disabled={busy || readOnly}
    />
    <button class="send" on:click={send} disabled={busy || readOnly || !text.trim()}>
      {busy ? '…' : '发送'}
    </button>
    <button class="toggle" class:on={panelOpen} on:click={onTogglePanel}>消息</button>
  </div>
</div>

<style>
  .dock-shell {
    position: absolute;
    left: 50%;
    bottom: 14px;
    transform: translateX(-50%);
    z-index: 25;
    width: min(760px, calc(100% - 48px));
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .dock {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 10px;
    background: linear-gradient(180deg, rgba(26, 38, 66, 0.96) 0%, rgba(18, 27, 49, 0.96) 100%);
    border: 1px solid var(--hairline);
    border-radius: 10px;
    box-shadow:
      0 6px 24px rgba(0, 0, 0, 0.5),
      0 0 0 1px rgba(217, 186, 125, 0.08);
    font-size: 13px;
  }
  .refs-bar,
  .preview {
    padding: 8px 10px;
    background: rgba(18, 27, 49, 0.97);
    border: 1px solid var(--hairline);
    border-radius: 8px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
    color: var(--text);
    font-size: 11px;
  }
  .refs-head,
  .preview header {
    display: flex;
    align-items: center;
    gap: 9px;
    color: var(--gold-dim);
  }
  .refs-head {
    justify-content: space-between;
    margin-bottom: 6px;
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
    max-width: 250px;
    padding: 3px 5px 3px 7px;
    border: 1px solid var(--hairline);
    border-radius: 999px;
    background: var(--panel-3);
  }
  .ref-chip b {
    color: var(--gold);
    font-size: 9px;
    text-transform: uppercase;
  }
  .ref-chip > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ref-chip button {
    padding: 0 3px;
    border: 0;
    background: transparent;
  }
  .pin {
    color: var(--muted);
  }
  .pin.pinned {
    color: var(--gold-bright);
  }
  .remove {
    color: var(--muted);
    font-size: 14px;
  }
  .preview-button {
    padding: 3px 8px;
  }
  .preview {
    max-height: min(42vh, 360px);
    overflow: auto;
  }
  .preview.error {
    color: var(--red);
  }
  .preview header {
    margin-bottom: 5px;
  }
  .preview header strong {
    color: var(--gold-bright);
  }
  .preview header span {
    margin-left: auto;
  }
  .preview summary {
    cursor: pointer;
    color: var(--text);
    padding: 3px 0;
  }
  .preview pre {
    margin: 3px 0 7px;
    padding: 7px;
    border-radius: 5px;
    background: #0b1222;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: 10px;
  }
  .context {
    color: var(--gold-dim);
    font-size: 11px;
    white-space: nowrap;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    user-select: none;
  }
  input {
    flex: 1;
    min-width: 0;
    background: var(--panel-3);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 6px;
    padding: 6px 10px;
    font: inherit;
  }
  input:focus {
    outline: none;
    border-color: var(--gold-dim);
    box-shadow: 0 0 0 2px rgba(217, 186, 125, 0.15);
  }
  button {
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--hairline);
    border-radius: 6px;
    padding: 5px 12px;
    cursor: pointer;
    font: inherit;
  }
  button:hover:not(:disabled) {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .toggle.on {
    border-color: var(--gold);
    color: var(--gold-bright);
  }
</style>
