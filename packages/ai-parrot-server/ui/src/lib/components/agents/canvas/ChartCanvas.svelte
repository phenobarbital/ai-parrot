<script lang="ts">
	import DataChart from '../DataChart.svelte';
	import DataMap from '../DataMap.svelte';

	let { data }: { data: unknown } = $props();

	// data shape: { charts: Array<{ data: Record<string,any>[], config: object }> } | '__loading__'
	let isLoading = $derived(data === '__loading__');

	interface ChartEntry {
		data: Record<string, any>[];
		config: {
			type: string;
			x: string;
			y: string[];
			stacked?: boolean;
			trendline?: boolean;
			splitSeries?: boolean;
			title?: string;
			showLegend?: boolean;
			// Map-specific config
			mapLatColumn?: string;
			mapLngColumn?: string;
			mapLabelColumns?: string[];
			mapLabelColumn?: string;
			mapMarkerColor?: string;
		};
	}

	let payload = $derived(
		typeof data === 'object' && data !== null && !Array.isArray(data)
			? (data as { charts?: ChartEntry[] })
			: null
	);

	let charts = $derived(payload?.charts ?? []);

	function removeChart(index: number) {
		if (!payload?.charts) return;
		payload.charts = payload.charts.filter((_, i) => i !== index);
	}
</script>

<div class="flex flex-col h-full overflow-y-auto p-4 gap-4">
	{#if isLoading}
		<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3">
			<p class="text-sm font-medium">Loading chart...</p>
		</div>
	{:else if charts.length > 0}
		{#each charts as chart, i (i)}
			{#if chart.config.type === 'map'}
				<DataMap
					data={chart.data}
					config={chart.config}
					onClose={() => removeChart(i)}
				/>
			{:else}
				<DataChart
					data={chart.data}
					config={chart.config}
					onClose={() => removeChart(i)}
				/>
			{/if}
		{/each}
	{:else}
		<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6">
			<p class="text-sm font-medium">No Charts</p>
			<p class="text-xs mt-1">Use "Copy to Chart Canvas" on a chart to add it here.</p>
		</div>
	{/if}
</div>
