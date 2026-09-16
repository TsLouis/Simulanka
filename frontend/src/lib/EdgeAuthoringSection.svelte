<script lang="ts">
  import ObjectStructuralActions from './ObjectStructuralActions.svelte'
  import { objectAction } from './object-authoring'
  import type { EdgeDTO } from './types'

  export let edge: EdgeDTO
  export let onDisconnect: () => void = () => {}

  $: disconnectAction = objectAction(edge.affordances, 'edge.delete')
</script>

{#if disconnectAction}
  <ObjectStructuralActions {disconnectAction} {onDisconnect} />
{/if}
