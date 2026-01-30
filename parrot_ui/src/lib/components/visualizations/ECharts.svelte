<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import * as echarts from 'echarts';

	interface Props {
		options: any;
		theme?: string | object;
		className?: string;
		style?: string;
	}

	let {
		options,
		theme = 'light',
		className = '',
		style = 'width: 100%; height: 400px;'
	} = $props<Props>();

	let chartContainer: HTMLDivElement;
	let chartInstance: echarts.ECharts | null = null;

	// Effect to initialize and update chart when options change
	// Using $effect to react to options changes in Svelte 5
	$effect(() => {
		if (chartContainer && options) {
			initOrUpdateChart();
		}
	});

	function initOrUpdateChart() {
		if (!chartInstance) {
			chartInstance = echarts.init(chartContainer, theme);
			// Add resize listener
			window.addEventListener('resize', handleResize);
		}

		// Ensure options are valid
		const safeOptions = typeof options === 'string' ? JSON.parse(options) : options;

		chartInstance.setOption(safeOptions, true); // true = notMerge (replace checks)
	}

	function handleResize() {
		chartInstance?.resize();
	}

	let resizeObserver: ResizeObserver;

	onDestroy(() => {
		if (typeof window !== 'undefined') {
			window.removeEventListener('resize', handleResize);
			resizeObserver?.disconnect();
		}
		chartInstance?.dispose();
		chartInstance = null;
	});

	// Watch container size changes
	$effect(() => {
		if (chartContainer) {
			resizeObserver = new ResizeObserver(() => {
				handleResize();
			});
			resizeObserver.observe(chartContainer);
		}
	});
</script>

<div bind:this={chartContainer} class={`echarts-container ${className}`} {style}></div>
