<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import embed from 'vega-embed';

	interface Props {
		spec: any; // Vega/Vega-Lite specification (JSON)
		options?: any; // Embed options
		className?: string;
		style?: string;
	}

	let {
		spec,
		options = {},
		className = '',
		style = 'width: 100%; min-height: 400px;'
	} = $props<Props>();

	let chartContainer = $state<HTMLDivElement>();
	let view = $state<any>(null);

	// Effect to initialize and update chart when spec changes
	$effect(() => {
		if (chartContainer && spec) {
			renderChart();
		}
	});

	async function renderChart() {
		if (!chartContainer) return;

		try {
			const result = await embed(chartContainer, spec, {
				actions: true,
				theme: 'dark', // Default to dark theme to match UI, can be overridden
				...options
			});
			view = result.view;
		} catch (error) {
			console.error('Error rendering Vega chart:', error);
			if (chartContainer) {
				chartContainer.innerHTML = `<div class="text-error p-4">Error rendering chart: ${error}</div>`;
			}
		}
	}

	onDestroy(() => {
		if (view) {
			view.finalize();
		}
	});
</script>

<div bind:this={chartContainer} class={`vega-chart-container ${className}`} {style}></div>
