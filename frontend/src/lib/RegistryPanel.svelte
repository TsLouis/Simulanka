<script lang="ts">
  import type { RegistryDescriptorDTO } from './types'

  export let descriptor: RegistryDescriptorDTO | null = null
  export let onClose: () => void = () => {}

  function parentLabel(parent: string | null): string {
    return parent === null ? 'top' : parent
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') onClose()
  }
</script>

<svelte:window on:keydown={onKeydown} />

<aside class="registry" aria-label="Registry 浏览器">
  <header>
    <div>
      <strong>Profile / Capability Registry</strong>
      <small>服务端当前加载的只读语义描述</small>
    </div>
    <button on:click={onClose} title="关闭 Registry (Esc)">✕</button>
  </header>

  {#if descriptor === null}
    <p class="empty">Registry descriptor 尚未加载。</p>
  {:else}
    <div class="body">
      <section class="identity" aria-label="Registry 标识">
        <div><span>Version</span><b>v{descriptor.version}</b></div>
        <div><span>Node Profiles</span><b>{descriptor.node_profiles.length}</b></div>
        <div><span>Edge Profiles</span><b>{descriptor.edge_profiles.length}</b></div>
        <div><span>Templates</span><b>{descriptor.templates.length}</b></div>
        <code title={descriptor.digest}>{descriptor.digest}</code>
      </section>

      <section>
        <h2>Packages</h2>
        <div class="chips">
          {#each descriptor.packages as packageName}
            <span>{packageName}</span>
          {/each}
        </div>
      </section>

      <section>
        <h2>Capabilities <small>{descriptor.capabilities.length}</small></h2>
        <div class="cards capability-cards">
          {#each descriptor.capabilities as capability (capability.key)}
            <article>
              <code>{capability.key}</code>
              <p>{capability.description}</p>
              <div class="chips subtle">
                {#each capability.consumers as consumer}
                  <span>{consumer}</span>
                {/each}
              </div>
            </article>
          {/each}
        </div>
      </section>

      <section>
        <h2>Node Profiles <small>{descriptor.node_profiles.length}</small></h2>
        <div class="cards profile-cards">
          {#each descriptor.node_profiles as profile (profile.key)}
            <article>
              <div class="row-title">
                <code>{profile.key}</code>
                {#if profile.lineage.length > 1}
                  <small>{profile.lineage.join(' → ')}</small>
                {/if}
              </div>
              <p>parent: {profile.allow_parents.map(parentLabel).join(', ') || 'none'}</p>
              <div class="chips subtle">
                {#each profile.capabilities as capability}
                  <span>{capability}</span>
                {/each}
                {#if profile.capabilities.length === 0}<i>no capabilities</i>{/if}
              </div>
            </article>
          {/each}
        </div>
      </section>

      <section>
        <h2>Edge Profiles <small>{descriptor.edge_profiles.length}</small></h2>
        <div class="table" aria-label="Edge Profiles">
          {#each descriptor.edge_profiles as profile (profile.key)}
            <div class="table-row">
              <code>{profile.key}</code>
              <span>{profile.needs_ports ? 'ports required' : 'node endpoints'}</span>
              <span>
                {profile.source_port_direction ?? 'node'} → {profile.target_port_direction ?? 'node'}
              </span>
            </div>
          {/each}
        </div>
      </section>

      <section>
        <h2>Templates <small>{descriptor.templates.length}</small></h2>
        <div class="table" aria-label="Templates">
          {#each descriptor.templates as template (template.key)}
            <div class="table-row template-row">
              <code>{template.key}</code>
              <span>{template.profile}</span>
              <span>{template.category}</span>
            </div>
          {/each}
        </div>
      </section>
    </div>
  {/if}
</aside>

<style>
  .registry {
    position: absolute;
    inset: 18px 18px 76px auto;
    z-index: 58;
    width: min(920px, calc(100% - 36px));
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--gold-dim);
    border-radius: 10px;
    background: linear-gradient(180deg, #111b30 0%, #0d172a 100%);
    box-shadow: 0 18px 52px rgba(0, 0, 0, 0.72);
    color: var(--text);
  }
  header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 11px 14px;
    border-bottom: 1px solid var(--hairline);
    background: var(--panel-2);
  }
  header div {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  header strong {
    color: var(--gold-bright);
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 500;
  }
  header small,
  h2 small {
    color: var(--muted);
    font-weight: 400;
  }
  button {
    border: 1px solid var(--hairline);
    border-radius: 5px;
    background: var(--panel-3);
    color: var(--text);
    cursor: pointer;
    padding: 3px 9px;
  }
  button:hover {
    border-color: var(--gold-dim);
    color: var(--ivory);
  }
  .body {
    min-height: 0;
    overflow: auto;
    padding: 14px 16px 24px;
  }
  section + section {
    margin-top: 18px;
  }
  h2 {
    margin: 0 0 8px;
    color: var(--ivory);
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 500;
  }
  h2 small {
    margin-left: 4px;
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .identity {
    display: grid;
    grid-template-columns: repeat(4, minmax(100px, 1fr));
    gap: 8px;
  }
  .identity div {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 9px 10px;
    border: 1px solid var(--hairline-2);
    border-radius: 6px;
    background: rgba(20, 30, 54, 0.72);
  }
  .identity span {
    color: var(--muted);
    font-size: 10px;
  }
  .identity b {
    color: var(--gold-bright);
    font-family: var(--font-mono);
    font-size: 17px;
  }
  .identity > code {
    grid-column: 1 / -1;
    color: var(--gold-dim);
    font-family: var(--font-mono);
    font-size: 10px;
    overflow-wrap: anywhere;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }
  .chips span {
    padding: 2px 7px;
    border: 1px solid rgba(217, 186, 125, 0.32);
    border-radius: 999px;
    color: var(--gold-bright);
    background: rgba(217, 186, 125, 0.07);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .chips.subtle span {
    border-color: var(--hairline);
    color: #aebbd1;
    background: rgba(46, 61, 91, 0.3);
  }
  .chips i {
    color: var(--muted);
    font-size: 10px;
  }
  .cards {
    display: grid;
    gap: 7px;
  }
  .capability-cards {
    grid-template-columns: repeat(2, minmax(220px, 1fr));
  }
  .profile-cards {
    grid-template-columns: repeat(3, minmax(190px, 1fr));
  }
  article {
    min-width: 0;
    padding: 8px 9px;
    border: 1px solid var(--hairline-2);
    border-radius: 6px;
    background: rgba(9, 17, 31, 0.46);
  }
  article code,
  .table code {
    color: var(--jade);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  article p {
    margin: 5px 0 7px;
    color: var(--muted);
    font-size: 10px;
    line-height: 1.4;
  }
  .row-title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 7px;
  }
  .row-title small {
    overflow: hidden;
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 9px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .table {
    overflow: hidden;
    border: 1px solid var(--hairline-2);
    border-radius: 6px;
  }
  .table-row {
    display: grid;
    grid-template-columns: minmax(150px, 1.2fr) minmax(120px, 0.8fr) minmax(120px, 0.8fr);
    gap: 10px;
    align-items: center;
    padding: 6px 9px;
    color: var(--muted);
    background: rgba(9, 17, 31, 0.38);
    font-size: 10px;
  }
  .table-row + .table-row {
    border-top: 1px solid var(--hairline-2);
  }
  .template-row {
    grid-template-columns: minmax(220px, 1.4fr) minmax(100px, 0.6fr) minmax(150px, 0.8fr);
  }
  .empty {
    margin: 18px;
    color: var(--amber);
  }
  @media (max-width: 760px) {
    .identity,
    .capability-cards,
    .profile-cards {
      grid-template-columns: 1fr 1fr;
    }
    .table-row,
    .template-row {
      grid-template-columns: 1fr;
      gap: 2px;
    }
  }
</style>
