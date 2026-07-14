<script lang="ts">
  // 底部常驻输入条:只做输入(用户拍板 2026-07-12)。对话历史在会话节点
  // (ChatNode)里;锚定=当前画布选中集,没选中就锚定当前容器。
  export let anchorLabel: string
  export let busy = false
  export let panelOpen = false
  export let onSend: (text: string) => void
  export let onTogglePanel: () => void

  let text = ''

  function send() {
    const t = text.trim()
    if (!t || busy) return
    text = ''
    onSend(t)
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      send()
    }
  }
</script>

<div class="dock">
  <span class="anchor" title="消息锚定在这里(§13.6:对话必锚定画布选择)">
    ⚓ {anchorLabel}
  </span>
  <input
    placeholder="给 agent 留话…(Enter 发送)"
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
  .anchor {
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
