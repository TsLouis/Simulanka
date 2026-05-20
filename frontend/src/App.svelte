<script lang="ts">
  import { onMount } from 'svelte'
  import { LGraphCanvas } from 'litegraph.js'
  import 'litegraph.js/css/litegraph.css'
  import { fetchGraph } from './lib/api'
  import { buildLiteGraph } from './lib/litegraph-adapter'

  let canvasEl: HTMLCanvasElement
  let rootInput = ''
  let depth = 1
  let status = 'idle'
  let nodeCount = 0
  let edgeCount = 0

  let lgcanvas: LGraphCanvas | null = null

  async function load() {
    status = 'loading…'
    try {
      const payload = await fetchGraph(rootInput.trim() || null, depth)
      const { graph } = buildLiteGraph(payload)
      if (lgcanvas) {
        lgcanvas.setGraph(graph)
      } else {
        lgcanvas = new LGraphCanvas(canvasEl, graph)
      }
      graph.start()
      nodeCount = payload.nodes.length
      edgeCount = payload.edges.length
      status = payload.root ? `root=${payload.root}` : 'top-level'
    } catch (err) {
      status = `error: ${(err as Error).message}`
    }
  }

  onMount(() => {
    void load()
  })
</script>

<header>
  <strong>Simulanka</strong>
  <label>root <input bind:value={rootInput} placeholder="(top-level)" /></label>
  <label>depth <input type="number" min="0" max="5" bind:value={depth} /></label>
  <button on:click={load}>Load</button>
  <span class="status">{status} · {nodeCount}n / {edgeCount}e</span>
</header>

<canvas bind:this={canvasEl} width="1600" height="900"></canvas>

<style>
  :global(body, html) {
    margin: 0;
    padding: 0;
    background: #1a1a1a;
    color: #ddd;
    font-family: ui-sans-serif, system-ui, sans-serif;
  }
  header {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 8px 12px;
    background: #222;
    border-bottom: 1px solid #333;
    font-size: 13px;
  }
  header input {
    background: #111;
    color: #ddd;
    border: 1px solid #444;
    padding: 2px 6px;
    font-family: inherit;
    font-size: 13px;
  }
  header input[type='number'] {
    width: 50px;
  }
  header button {
    background: #333;
    color: #ddd;
    border: 1px solid #555;
    padding: 3px 10px;
    cursor: pointer;
  }
  header button:hover {
    background: #444;
  }
  .status {
    margin-left: auto;
    color: #999;
    font-family: ui-monospace, monospace;
  }
  canvas {
    display: block;
    width: 100vw;
    height: calc(100vh - 41px);
  }
</style>
