<script lang="ts">
	// ai-parrot (FEAT-476 TASK-2595): AppChart (layerchart) — gated behind
	// features.charts (spec §3 Module 5 "gate cross-surface imports").
	import { features } from '$lib/features';
	import type { AppChartConfig } from '$lib/components/charts/chart-contract.js';
	import type { ChartBlockData, ChartType } from '../infographic-types';

	let {
		chart_type,
		title,
		description,
		labels,
		series,
		x_axis_label: _x_axis_label,
		y_axis_label: _y_axis_label,
		stacked,
		show_legend,
		color_by_sign,
		positive_color,
		negative_color
	}: ChartBlockData = $props();

	// Defaults match the infographic sentiment palette.
	const DEFAULT_POSITIVE = '#22c55e';
	const DEFAULT_NEGATIVE = '#ef4444';

	/**
	 * Map infographic ChartType to AppChartConfig type.
	 * Types not in AppChart (heatmap, treemap, funnel, gauge, waterfall) fall
	 * back to 'bar' — a best-effort approximation.
	 */
	function toAppChartType(
		t: ChartType
	): AppChartConfig['type'] {
		switch (t) {
			case 'bar':
				return 'bar';
			case 'line':
				return 'line';
			case 'area':
				return 'area';
			case 'scatter':
				return 'scatter';
			case 'pie':
				return 'pie';
			case 'donut':
				return 'donut';
			case 'radar':
				return 'radar';
			default:
				// heatmap, treemap, funnel, gauge, waterfall → bar (not yet supported)
				return 'bar';
		}
	}

	/**
	 * Transform infographic series+labels to the flat-row format AppChart expects.
	 * Output: [{ _label: "Jan", "Revenue": 100, "Cost": 50 }, ...]
	 */
	function buildRows(
		lbls: string[],
		ser: ChartBlockData['series']
	): Record<string, unknown>[] {
		return lbls.map((lbl, i) => {
			const row: Record<string, unknown> = { _label: lbl };
			for (const s of ser) {
				row[s.name] = s.values[i] ?? null;
			}
			return row;
		});
	}

	let chartData = $derived(buildRows(labels, series));

	let yKeys = $derived(series.map((s) => s.name));

	/**
	 * Build the AppChartConfig from infographic block data.
	 */
	let appChartConfig = $derived.by((): AppChartConfig => {
		const type = toAppChartType(chart_type);

		// When color_by_sign is active, let AppChart color each bar by the sign of its
		// value (positive_color for ≥0, negative_color for <0). Otherwise use per-series colors.
		if (color_by_sign) {
			return {
				type,
				x: '_label',
				y: yKeys.length > 0 ? yKeys : ['_value'],
				stacked: stacked ?? false,
				showLegend: show_legend ?? true,
				colorBySign: true,
				palette: [positive_color || DEFAULT_POSITIVE],
				negativeColor: negative_color || DEFAULT_NEGATIVE
			};
		}

		const seriesColors = series.map((s) => s.color).filter(Boolean) as string[];
		const palette =
			seriesColors.length === series.length ? seriesColors : undefined;

		return {
			type,
			x: '_label',
			y: yKeys.length > 0 ? yKeys : ['_value'],
			stacked: stacked ?? false,
			showLegend: show_legend ?? true,
			...(palette ? { palette } : {})
		};
	});
</script>

<div class="rounded-lg border border-border bg-card p-4">
	{#if title}
		<h3 class="mb-1 text-sm font-semibold text-foreground">{title}</h3>
	{/if}
	{#if description}
		<p class="mb-3 text-xs text-muted-foreground">{description}</p>
	{/if}
	<div class="h-80 w-full">
		{#if features.charts}
			{#await import('$lib/components/charts/AppChart.svelte') then { default: AppChart }}
				<AppChart config={appChartConfig} data={chartData} />
			{/await}
		{:else}
			<div class="flex h-full w-full items-center justify-center rounded-md border border-dashed border-border bg-muted/30 text-sm text-muted-foreground">
				Chart feature disabled in this build.
			</div>
		{/if}
	</div>
</div>
