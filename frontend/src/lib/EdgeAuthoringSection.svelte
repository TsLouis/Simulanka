<script lang="ts">
  import ObjectStructuralActions from './ObjectStructuralActions.svelte'
  import { edgeAction } from './object-authoring'
  import type { EdgeDTO } from './types'

  export let edge: EdgeDTO
  export let onDisconnect: () => void = () => {}

  $: disconnectAction = edgeAction(edge, 'edge.delete')
</script>

{#if disconnectAction}
  <ObjectStructuralActions {disconnectAction} {onDisconnect} />
{/if}
