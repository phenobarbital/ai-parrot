<script lang="ts">
	import { browser } from '$app/environment';
	import type { TableBlockData } from '../canvas-block-types';

	let { data }: { data: TableBlockData } = $props();

	let RevoGrid = $state<any>(null);
	let height = $state<number>(400);
	let isResizing = $state(false);

	$effect(() => {
		if (browser && !RevoGrid) {
			import('@revolist/svelte-datagrid').then((mod) => {
				RevoGrid = mod.RevoGrid;
			});
		}
	});

	let columns = $derived(
		(data.columns ?? (data.rows.length > 0 ? Object.keys(data.rows[0]) : [])).map((col) => ({
			prop: col,
			name: col,
			sortable: true,
			filter: true,
			size: 150
		}))
	);

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

<div class="relative rounded-md overflow-hidden border border-border" style="height: {height}px;">
	{#if browser && RevoGrid && data.rows.length > 0}
		<svelte:component
			this={RevoGrid}
			source={data.rows}
			{columns}
			readonly={true}
			resize={true}
			filter={true}
			theme="compact"
			style="height: 100%; width: 100%;"
		/>
	{:else}
		<!-- Fallback HTML table during SSR / loading -->
		<div class="overflow-x-auto h-full">
			{#if data.rows.length === 0}
				<p class="text-sm text-muted-foreground p-3">No data to display.</p>
			{:else}
				{@const cols = data.columns ?? Object.keys(data.rows[0])}
				<table class="w-full text-sm border-collapse">
					<thead>
						<tr>
							{#each cols as col}
								<th class="border border-border px-2 py-1 text-left font-medium bg-muted/30 whitespace-nowrap">{col}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each data.rows.slice(0, 50) as row, i}
							<tr class={i % 2 === 0 ? 'bg-background' : 'bg-muted/20'}>
								{#each cols as col}
									<td class="border border-border px-2 py-1 whitespace-nowrap">{row[col] ?? ''}</td>
								{/each}
							</tr>
						{/each}
						{#if data.rows.length > 50}
							<tr>
								<td colspan={cols.length} class="text-center text-muted-foreground text-xs py-2 border border-border">
									... and {data.rows.length - 50} more rows
								</td>
							</tr>
						{/if}
					</tbody>
				</table>
			{/if}
		</div>
	{/if}

	<!-- Resize handle -->
	<button
		class="absolute bottom-0 right-0 w-6 h-6 cursor-se-resize bg-gradient-to-tl from-primary/40 to-transparent hover:from-primary/60 border-t border-l border-primary/50 hover:border-primary transition-all"
		onmousedown={startResize}
		title="Drag to resize"
		aria-label="Resize block"
		style="transform: translate(0.5px, 0.5px); border-radius: 0 0 3px 0;"
	></button>
</div>
