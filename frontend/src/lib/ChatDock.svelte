<script lang="ts">
  // 底部常驻输入条只负责消息和显式上下文提示；画布选择不会被静默注入。
  export let contextLabel: string
  export let busy = false
  export let panelOpen = false
  export let onSend: (text: string) => void
  export let onTogglePanel: () => void

  let text = ''

  function send() {
    if (!text.trim() || busy) return
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

<div class="dock">
  <span class="context" title="只发送你显式附加的上下文">
    ◇ {contextLabel}
  </span>
  <input
    placeholder="直接和 agent 对话…（Enter 发送）"
    bind:value={text}
    on:keydown={onKeydown}
    disabled={busy}
  />
  <button class="send" on:click={send} disabled={busy || !text.trim()}>
    {busy ? '…' : '发送'}
  </button>
  <button class="toggle" class:on={panelOpen} on:click={onTogglePanel}>消息</button>
</div>

<style>
  .dock {
    position: absolute;
    left: 50%;
    bottom: 14px;
    transform: translateX(-50%);
    z-index: 25;
    display: flex;
    align-items: center;
    gap: 8px;
    width: min(640px, calc(100% - 48px));
    padding: 7px 10px;
    background: linear-gradient(180deg, rgba(26, 38, 66, 0.96) 0%, rgba(18, 27, 49, 0.96) 100%);
    border: 1px solid var(--hairline);
    border-radius: 10px;
    box-shadow:
      0 6px 24px rgba(0, 0, 0, 0.5),
      0 0 0 1px rgba(217, 186, 125, 0.08);
    font-size: 13px;
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
