<script lang="ts">
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import WidgetShell from '../WidgetShell.svelte';
	import WidgetRenderer from '../WidgetRenderer.svelte';

	let { dashboard } = $props<{ dashboard: Dashboard }>();
</script>

<div class="relative h-full w-full overflow-auto">
	<!-- Visual background hint -->
	<div
		class="pointer-events-none absolute inset-0 bg-[radial-gradient(#000000_1px,transparent_1px)] opacity-10 [background-size:20px_20px]"
	></div>

	{#each dashboard.widgets as widget (widget.id)}
		<WidgetShell {widget} layoutMode="free" on:close={() => dashboard.removeWidget(widget.id)}>
			<WidgetRenderer {widget} />
		</WidgetShell>
	{/each}
</div>
