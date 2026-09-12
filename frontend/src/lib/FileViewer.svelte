<script lang="ts">
  // S4 通用文件查看器：只读文档抽屉。任何 kind 的 file 节点通吃 —— markdown
  // 渲染，其余纯文本预格式化。「打开并高亮一个词」是通用参数：深链出处传
  // plan_lid（先试带引号的精确形，再试裸词，找不到退化开顶部）。不做编辑、
  // 不做双向同步 —— 图是文档的有损投影，这里是投影可逆性的人面保证。
  import { tick } from 'svelte'
  import { marked } from 'marked'
  import DOMPurify from 'dompurify'
  import { fetchFileContent, type FileContentDTO, type FileOpenRequest } from './api'

  export let request: FileOpenRequest
  export let onClose: () => void

  let doc: FileContentDTO | null = null
  let error: string | null = null
  let bodyEl: HTMLElement | null = null

  $: void load(request)

  async function load(req: FileOpenRequest) {
    doc = null
    error = null
    try {
      doc = await fetchFileContent(req)
      await tick()
      if (req.highlight) highlightTerm(req.highlight)
    } catch (err) {
      error = (err as Error).message
    }
  }

  $: isMarkdown = doc?.fs_path.endsWith('.md') ?? false
  $: html =
    doc && isMarkdown && doc.content !== null
      ? DOMPurify.sanitize(marked.parse(doc.content, { async: false }))
      : null

  // Wrap the first occurrence in <mark> and scroll it into view. Candidates in
  // precision order: the JSON-quoted form ("q1" as it appears inside the plan
  // block), then the bare term. Not found → stay at the top (spec: 退化开顶部).
  function highlightTerm(term: string) {
    if (!bodyEl) return
    for (const cand of [`"${term}"`, term]) {
      const walker = document.createTreeWalker(bodyEl, NodeFilter.SHOW_TEXT)
      let tn: Node | null
      while ((tn = walker.nextNode())) {
        const idx = tn.textContent?.indexOf(cand) ?? -1
        if (idx < 0) continue
        const range = document.createRange()
        range.setStart(tn, idx)
        range.setEnd(tn, idx + cand.length)
        const mark = document.createElement('mark')
        mark.className = 'hl'
        range.surroundContents(mark)
        mark.scrollIntoView({ block: 'center' })
        return
      }
    }
  }

  function fmtSize(n: number): string {
    if (n < 1024) return `${n} B`
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
    return `${(n / 1024 / 1024).toFixed(1)} MB`
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose()
  }
</script>

<svelte:window on:keydown={onKeydown} />

<aside class="viewer" aria-label="file viewer">
  <header>
    <div class="title">
      {#if doc}
        <span class="kind-chip">{doc.kind ?? 'file'}</span>
        <span class="name">{doc.name}</span>
      {:else}
        <span class="name muted">加载中…</span>
      {/if}
      <button class="close" on:click={onClose} title="关闭 (Esc)">✕</button>
    </div>
    {#if doc}
      <div class="meta">
        <code class="path">{doc.fs_path}</code>
        <span class="size">{fmtSize(doc.size_bytes)}</span>
      </div>
    {/if}
  </header>

  <div class="body" bind:this={bodyEl}>
    {#if error}
      <p class="error">{error}</p>
    {:else if doc}
      {#if doc.binary}
        <p class="notice">二进制文件，无法预览（{fmtSize(doc.size_bytes)}）。</p>
      {:else if html !== null}
        <!-- eslint-disable-next-line svelte/no-at-html-tags — DOMPurify-sanitized -->
        <div class="markdown">{@html html}</div>
      {:else if doc.content !== null}
        <pre class="plain">{doc.content}</pre>
      {/if}
      {#if doc.truncated}
        <p class="notice">⚠ 文件超出预览上限，仅显示前 {fmtSize(1048576)}。</p>
      {/if}
    {/if}
  </div>
</aside>

<style>
  /* File drawer opens from the right edge. */
  .viewer {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(680px, 58vw);
    display: flex;
    flex-direction: column;
    background: linear-gradient(180deg, var(--panel) 0%, #101a30 100%);
    border-left: 1px solid var(--gold-dim);
    box-shadow: -18px 0 42px rgba(0, 0, 0, 0.5);
    color: var(--text);
    z-index: 30;
  }
  header {
    padding: 12px 16px 10px;
    border-bottom: 1px solid var(--hairline-2);
  }
  .title {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .kind-chip {
    background: var(--panel-2);
    border: 1px solid var(--gold-dim);
    color: var(--gold);
    padding: 1px 7px;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .name {
    font-family: var(--font-display);
    font-size: 15px;
    color: var(--ivory);
    flex: 1;
    word-break: break-all;
  }
  .muted {
    color: var(--muted);
  }
  .close {
    background: transparent;
    border: 1px solid var(--hairline);
    border-radius: 4px;
    color: var(--muted);
    cursor: pointer;
    padding: 2px 8px;
    font-size: 12px;
  }
  .close:hover {
    color: var(--ivory);
    border-color: var(--gold-dim);
  }
  .meta {
    margin-top: 6px;
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .path {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--muted);
    word-break: break-all;
  }
  .size {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--gold-dim);
    white-space: nowrap;
  }
  .body {
    flex: 1;
    overflow: auto;
    padding: 14px 18px 28px;
    font-size: 13px;
    line-height: 1.55;
  }
  .plain {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 12px;
    color: #c4d3e8;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .error {
    color: var(--crimson);
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .notice {
    color: var(--amber);
    background: rgba(58, 47, 28, 0.4);
    border: 1px solid rgba(217, 186, 125, 0.25);
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 12px;
  }
  .body :global(mark.hl) {
    background: var(--gold);
    color: #1a2642;
    padding: 0 3px;
    border-radius: 3px;
    box-shadow: 0 0 10px var(--gold-glow);
  }
  /* Markdown document typography. */
  .markdown :global(h1),
  .markdown :global(h2),
  .markdown :global(h3) {
    font-family: var(--font-display);
    font-weight: 400;
    color: var(--ivory);
    border-bottom: 1px solid var(--hairline-2);
    padding-bottom: 4px;
  }
  .markdown :global(h1) {
    font-size: 19px;
  }
  .markdown :global(h2) {
    font-size: 16px;
  }
  .markdown :global(h3) {
    font-size: 14px;
  }
  .markdown :global(a) {
    color: var(--jade);
  }
  .markdown :global(code) {
    font-family: var(--font-mono);
    font-size: 12px;
    background: var(--panel-3);
    border-radius: 3px;
    padding: 1px 4px;
  }
  .markdown :global(pre) {
    background: var(--panel-3);
    border: 1px solid var(--hairline-2);
    border-radius: 5px;
    padding: 10px 12px;
    overflow-x: auto;
  }
  .markdown :global(pre code) {
    background: transparent;
    padding: 0;
    color: #c4d3e8;
  }
  .markdown :global(blockquote) {
    margin: 0 0 0 2px;
    padding-left: 12px;
    border-left: 2px solid var(--gold-dim);
    color: var(--muted);
  }
  .markdown :global(table) {
    border-collapse: collapse;
  }
  .markdown :global(th),
  .markdown :global(td) {
    border: 1px solid var(--hairline-2);
    padding: 3px 8px;
  }
</style>
