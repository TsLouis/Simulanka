<script lang="ts">
  import ObjectStructuralActions from './ObjectStructuralActions.svelte'
  import PortAuthoringSection from './PortAuthoringSection.svelte'
  import { objectAction, type CreatePortRequest, type UpdatePortRequest } from './object-authoring'
  import type { NodeDTO, PortDTO, RegistryDescriptorDTO } from './types'

  export let node: NodeDTO
  export let portsById: Map<string, PortDTO>
  export let registryDescriptor: RegistryDescriptorDTO | null = null
  export let onRename: () => void = () => {}
  export let onDelete: () => void = () => {}
  export let onAttachPort: (port: PortDTO) => void = () => {}
  export let onCreatePort: (request: CreatePortRequest) => void = () => {}
  export let onUpdatePort: (port: PortDTO, request: UpdatePortRequest) => void = () => {}
  export let onDeletePort: (port: PortDTO) => void = () => {}

  $: renameAction = objectAction(node.affordances, 'node.rename')
  $: deleteAction = objectAction(node.affordances, 'node.delete')
</script>

<div class="authoring">
  <PortAuthoringSection
    {node}
    {portsById}
    {registryDescriptor}
    {onAttachPort}
    {onCreatePort}
    {onUpdatePort}
    {onDeletePort}
  />

  <ObjectStructuralActions
    {renameAction}
    {deleteAction}
    onRename={onRename}
    onDelete={onDelete}
  />
</div>

<style>
  .authoring {
    display: flex;
    flex-direction: column;
    gap: 9px;
  }
</style>
