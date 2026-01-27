<script lang="ts">
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import GridLayout from './layouts/GridLayout.svelte';
	import FreeLayout from './layouts/FreeLayout.svelte';
	import DockLayout from './layouts/DockLayout.svelte';

	let { dashboard } = $props<{ dashboard: Dashboard }>();
</script>

<div class="dashboard-canvas bg-base-200/30 h-full w-full">
	{#if dashboard.layoutMode === 'grid'}
		<GridLayout {dashboard} />
	{:else if dashboard.layoutMode === 'free'}
		<FreeLayout {dashboard} />
	{:else}
		<DockLayout {dashboard} />
	{/if}

	{#if dashboard.widgets.length === 0}
		<div class="pointer-events-none absolute inset-0 flex items-center justify-center">
			<div class="text-center opacity-30">
				<div class="mb-2 text-4xl">📋</div>
				<div>Empty Dashboard</div>
				<div class="text-xs">Add a widget to get started</div>
			</div>
		</div>
	{/if}
</div>
