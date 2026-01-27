<script lang="ts">
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import WidgetShell from '../WidgetShell.svelte';
	import WidgetRenderer from '../WidgetRenderer.svelte';

	let { dashboard } = $props<{ dashboard: Dashboard }>();

	let containerWidth = $state(0);

	let containerStyle = $derived(`
        display: grid;
        grid-template-columns: repeat(${dashboard.gridConfig.cols}, 1fr);
        grid-auto-rows: ${dashboard.gridConfig.rowHeight}px;
        gap: ${dashboard.gridConfig.gap}px;
        width: 100%;
        padding: 16px;
    `);
</script>

<div class="min-h-full" style={containerStyle} bind:clientWidth={containerWidth}>
	{#each dashboard.widgets as widget (widget.id)}
		<WidgetShell
			{widget}
			gridConfig={dashboard.gridConfig}
			{containerWidth}
			layoutMode="grid"
			on:close={() => dashboard.removeWidget(widget.id)}
		>
			<WidgetRenderer {widget} />
		</WidgetShell>
	{/each}
</div>
