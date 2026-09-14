<script lang="ts">
  import type { FileOpenRequest } from './api'
  import type { AgentSessionController } from './agent-session'
  import type { NodeDTO, PortDTO, RegistryDescriptorDTO } from './types'
  import ActivityBar from './ActivityBar.svelte'
  import AgentCompanion from './AgentCompanion.svelte'
  import FileViewer from './FileViewer.svelte'
  import NodeInspector from './NodeInspector.svelte'
  import RegistryPanel from './RegistryPanel.svelte'

  export let selectedNode: NodeDTO | null
  export let portsById: Map<string, PortDTO>
  export let registryDescriptor: RegistryDescriptorDTO | null
  export let agent: AgentSessionController
  export let onJumpTo: (id: string) => void
  export let onResolveNote: (id: string) => void

  let inspectorOpen = false
  let registryOpen = false
  let discussionOpen = false
  let recoveryOpen = false
  let fileRequest: FileOpenRequest | null = null
  let lastFileRequest: FileOpenRequest | null = null
  let companion: AgentCompanion

  $: availableFile = selectedNode?.type === 'file'
    ? { node: selectedNode.id } : lastFileRequest

  function openFile(request: FileOpenRequest) {
    lastFileRequest = request
    fileRequest = request
  }
</script>

<div class="workspace">
  <slot name="topbar" />
  <div class="workspace-body">
    <ActivityBar
      {inspectorOpen}
      canInspect={selectedNode !== null}
      {registryOpen}
      filesOpen={fileRequest !== null}
      canOpenFile={availableFile !== null}
      {discussionOpen}
      {recoveryOpen}
      onInspector={() => (inspectorOpen = !inspectorOpen)}
      onRegistry={() => (registryOpen = !registryOpen)}
      onFiles={() => { if (fileRequest) fileRequest = null; else if (availableFile) openFile(availableFile) }}
      onDiscussion={() => { if (discussionOpen) discussionOpen = false; else companion.openDiscussion() }}
      onRecovery={() => { if (recoveryOpen) recoveryOpen = false; else companion.openRecovery() }}
    />
    <main>
      <slot />
      <NodeInspector
        node={selectedNode}
        bind:expanded={inspectorOpen}
        {portsById}
        {registryDescriptor}
        onOpenFile={openFile}
        {onJumpTo}
        {onResolveNote}
        onAttachNode={(node) =>
          agent.addPendingRef({ kind: 'node', ref_id: node.id }, `${node.type} · ${node.name}`)}
        onAttachPort={(port) =>
          agent.addPendingRef(
            { kind: 'port', ref_id: port.id },
            `port · ${selectedNode?.name ?? port.node_id}/${port.name}`,
          )}
      />
      {#if fileRequest}
        <FileViewer request={fileRequest} onClose={() => (fileRequest = null)} />
      {/if}
      <AgentCompanion bind:this={companion} controller={agent} bind:discussionOpen bind:recoveryOpen />
      {#if registryOpen}
        <RegistryPanel descriptor={registryDescriptor} onClose={() => (registryOpen = false)} />
      {/if}
    </main>
  </div>
</div>

<style>
  .workspace { display: flex; flex-direction: column; width: 100%; height: 100%; }
  .workspace-body { display: flex; flex: 1; min-height: 0; }
  main { position: relative; flex: 1; min-width: 0; min-height: 0; }
</style>
