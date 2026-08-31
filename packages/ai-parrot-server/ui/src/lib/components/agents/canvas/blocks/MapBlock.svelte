<script lang="ts">
	import type { MapBlockData } from '../canvas-block-types';
	// ai-parrot (FEAT-476 TASK-2595): DataMap pulls in leaflet — gated
	// behind features.maps (spec §3 Module 5 "gate cross-surface
	// imports"). A saved block whose feature is off renders a
	// "feature disabled in this build" placeholder instead.
	import { features } from '$lib/features';

	let {
		data,
		onDelete
	}: {
		data: MapBlockData;
		onDelete?: () => void;
	} = $props();
</script>

<div class="h-[400px] w-full">
	{#if features.maps}
		{#await import('../../DataMap.svelte') then { default: DataMap }}
			<DataMap data={data.data} config={data.config} onClose={onDelete} />
		{/await}
	{:else}
		<div class="flex h-full w-full items-center justify-center rounded-md border border-dashed border-border bg-muted/30 text-sm text-muted-foreground">
			Map feature disabled in this build.
		</div>
	{/if}
</div>
