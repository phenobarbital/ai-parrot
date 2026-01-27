<script lang="ts">
	import { marked } from 'marked';
	import DOMPurify from 'isomorphic-dompurify';
	import type { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';
	import DataTable from '$lib/components/agents/DataTable.svelte';
	import ECharts from '$lib/components/visualizations/ECharts.svelte';
	import Vega from '$lib/components/visualizations/Vega.svelte';

	let { widget } = $props<{ widget: AgentWidget }>();

	let content = $derived(widget.message.content || '');
	let outputMode = $derived(widget.message.output_mode || 'markdown');
	let data = $derived(widget.message.data);
	let output = $derived(
		widget.message.data || widget.message.output_mode === 'json' ? widget.message.data : null
	); // Normalized data

	let showData = $state(false);

	// Parse Markdown
	let parsedContent = $derived.by(() => {
		if (!content || outputMode !== 'markdown') return '';
		const raw = marked.parse(content);
		return DOMPurify.sanitize(raw as string);
	});

	// Determine render type
	let renderType = $derived.by(() => {
		if (outputMode === 'echarts') return 'echarts';
		if (outputMode === 'vega') return 'vega';
		if (outputMode === 'html' || content.trim().startsWith('<')) return 'html';
		return 'markdown';
	});

	// Normalized tool output for charts if present in separate field?
	// In legacy widget, it checked `message.output` too.
	// Assuming `widget.message.data` holds the struct for charts if `output_mode` is set.
</script>

<div class="group relative flex h-full flex-col">
	<!-- Main Content Area -->
	<div class="min-h-0 flex-1 overflow-auto p-4">
		{#if renderType === 'markdown'}
			<div class="prose prose-sm dark:prose-invert max-w-none">
				{@html parsedContent}
			</div>
			{#if content === ''}
				<div class="text-base-content/30 flex h-full items-center justify-center italic">
					Empty response
				</div>
			{/if}
		{:else if renderType === 'html'}
			<div class="h-full w-full rounded bg-white">
				<iframe
					srcdoc={content}
					class="h-full w-full border-0"
					sandbox="allow-scripts allow-same-origin"
					title="Agent Output"
				></iframe>
			</div>
		{:else if renderType === 'echarts'}
			<ECharts options={data} theme="dark" style="width: 100%; height: 100%; min-height: 300px;" />
		{:else if renderType === 'vega'}
			<Vega spec={data} style="width: 100%; height: 100%; min-height: 300px;" />
		{/if}
	</div>

	<!-- Data Overlay -->
	{#if showData && data}
		<div class="bg-base-100 absolute inset-0 z-10 flex flex-col overflow-auto">
			<div class="border-base-200 bg-base-200/50 flex items-center justify-between border-b p-2">
				<span class="text-xs font-bold uppercase tracking-wider">Data View</span>
				<button class="btn btn-xs btn-ghost" onclick={() => (showData = false)}>Close</button>
			</div>
			<div class="flex-1 overflow-auto p-4">
				{#if Array.isArray(data)}
					<DataTable {data} />
				{:else}
					<pre class="bg-base-300 overflow-auto rounded p-2 font-mono text-xs">{JSON.stringify(
							data,
							null,
							2
						)}</pre>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Footer / Actions -->
	{#if data}
		<div class="border-base-200 bg-base-100 flex justify-end border-t p-1">
			<button
				class="btn btn-xs btn-ghost gap-1 text-xs font-normal opacity-70 hover:opacity-100"
				onclick={() => (showData = !showData)}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="h-3 w-3"
				>
					<path
						fill-rule="evenodd"
						d="M10 2c-1.716 0-3.408.106-5.07.31C3.806 2.45 3 3.414 3 4.517V17.25a.75.75 0 0 0 1.075.676L10 15.082l5.925 2.844A.75.75 0 0 0 17 17.25V4.517c0-1.103-.806-2.068-1.93-2.207A41.403 41.403 0 0 0 10 2Z"
						clip-rule="evenodd"
					/>
				</svg>
				{showData ? 'Show Visual' : 'Show Data'}
			</button>
		</div>
	{/if}
</div>
