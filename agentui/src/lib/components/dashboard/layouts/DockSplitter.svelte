<script lang="ts">
	import type { DockState, DockNode } from './dock/types';
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import DockPane from './dock/DockPane.svelte';

	let { nodeId, dockState, dashboard } = $props<{
		nodeId: string;
		dockState: DockState;
		dashboard: Dashboard;
	}>();

	let node = $derived(dockState.nodes[nodeId]);

	// Derived styles
	let style = $derived.by(() => {
		if (!node) return '';
		return `
            display: flex;
            flex-direction: ${node.type === 'row' ? 'row' : 'column'};
            flex: ${node.size ? node.size : 1};
            width: 100%;
            height: 100%;
            overflow: hidden;
        `;
	});
</script>

{#if node}
	{#if node.type === 'pane'}
		<div
			class="border-base-300 bg-base-100 relative m-[1px] min-h-0 min-w-0 flex-1 overflow-hidden rounded-md border"
		>
			<DockPane paneId={node.paneId!} {dockState} {dashboard} />
		</div>
	{:else}
		<div {style}>
			{#each node.children as childId}
				<svelte:self nodeId={childId} {dockState} {dashboard} />
			{/each}
		</div>
	{/if}
{/if}
