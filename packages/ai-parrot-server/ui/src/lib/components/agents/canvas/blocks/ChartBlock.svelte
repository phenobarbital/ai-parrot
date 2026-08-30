<script lang="ts">
	import type { ChartBlockData } from '../canvas-block-types';
	// ai-parrot (FEAT-476 TASK-2595): DataChart pulls in AppChart
	// (layerchart, unconditional per spec) — gated behind features.charts
	// (spec §3 Module 5 "gate cross-surface imports"). A saved block
	// whose feature is off renders a "feature disabled in this build"
	// placeholder instead.
	import { features } from '$lib/features';
	import type DataChartComponent from '../../DataChart.svelte';

	let {
		data,
		onDelete
	}: {
		data: ChartBlockData;
		onDelete?: () => void;
	} = $props();

	let chartRef = $state<DataChartComponent | null>(null);
	let height = $state<number>(300);
	let isResizing = $state(false);

	/**
	 * Returns a PNG data URL of the chart for export.
	 * Calls DataChart's underlying Chart.js toBase64Image() via the component ref.
	 */
	export function getImageDataUrl(): string | null {
		// DataChart exposes chartInstance internally; we access it via the component
		// The actual toBase64Image is called within DataChart's onCopyToCanvas callback
		// For export, we trigger via a canvas element snapshot if available
		if (!chartRef) return null;
		// Access the underlying canvas element
		const canvas = document.querySelector<HTMLCanvasElement>(`[data-chart-block-id="${data.config.title || ''}"] canvas`);
		if (canvas) {
			try {
				return canvas.toDataURL('image/png');
			} catch {
				return null;
			}
		}
		return null;
	}

	function startResize(e: MouseEvent) {
		isResizing = true;
		const startY = e.clientY;
		const startHeight = height;

		function handleMouseMove(moveEvent: MouseEvent) {
			const delta = moveEvent.clientY - startY;
			height = Math.max(100, startHeight + delta);
		}

		function handleMouseUp() {
			isResizing = false;
			document.removeEventListener('mousemove', handleMouseMove);
			document.removeEventListener('mouseup', handleMouseUp);
		}

		document.addEventListener('mousemove', handleMouseMove);
		document.addEventListener('mouseup', handleMouseUp);
	}
</script>

<div class="relative rounded-md overflow-hidden border border-border bg-white dark:bg-slate-900" style="height: {height}px; min-height: 100px;" data-chart-block-id={data.config.title || ''}>
	<div class="h-full w-full">
		{#if features.charts}
			{#await import('../../DataChart.svelte') then { default: DataChart }}
				<DataChart
					bind:this={chartRef}
					data={data.data}
					config={data.config}
					compact={true}
				/>
			{/await}
		{:else}
			<div class="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
				Chart feature disabled in this build.
			</div>
		{/if}
	</div>

	<!-- Resize handle -->
	<button
		class="absolute bottom-0 right-0 z-20 w-6 h-6 cursor-se-resize bg-gradient-to-tl from-primary/40 to-transparent hover:from-primary/60 border-t border-l border-primary/50 hover:border-primary transition-all"
		onmousedown={startResize}
		title="Drag to resize"
		aria-label="Resize block"
		style="transform: translate(0.5px, 0.5px); border-radius: 0 0 3px 0;"
	></button>
</div>
