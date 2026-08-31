<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { InfographicBlock, InfographicBlockType } from './infographic-types';

	let {
		onInsert
	}: {
		onInsert: (block: InfographicBlock) => void;
	} = $props();

	let open = $state(false);

	function insert(block: InfographicBlock) {
		onInsert(block);
		open = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') open = false;
	}

	const contentBlocks: { type: InfographicBlockType; icon: string; label: string; factory: () => InfographicBlock }[] = [
		{ type: 'title', icon: 'mdi:format-title', label: 'Title', factory: () => ({ type: 'title', title: 'New Title' }) },
		{ type: 'summary', icon: 'mdi:text-box-outline', label: 'Summary', factory: () => ({ type: 'summary', content: '' }) },
		{ type: 'bullet_list', icon: 'mdi:format-list-bulleted', label: 'Bullet List', factory: () => ({ type: 'bullet_list', items: ['Item 1'] }) },
		{ type: 'image', icon: 'mdi:image', label: 'Image', factory: () => ({ type: 'image', url: '' }) },
	];

	const visualBlocks: { type: InfographicBlockType; icon: string; label: string; factory: () => InfographicBlock }[] = [
		{ type: 'hero_card', icon: 'mdi:card-text-outline', label: 'KPI Card', factory: () => ({ type: 'hero_card', label: 'Label', value: '0' }) },
		{ type: 'chart', icon: 'mdi:chart-bar', label: 'Chart', factory: () => ({ type: 'chart', chart_type: 'bar', labels: ['A', 'B', 'C'], series: [{ name: 'Series 1', values: [10, 20, 30] }] }) },
		{ type: 'table', icon: 'mdi:table', label: 'Table', factory: () => ({ type: 'table', columns: ['Column 1', 'Column 2'], rows: [['—', '—']] }) },
		{ type: 'callout', icon: 'mdi:alert-box-outline', label: 'Callout', factory: () => ({ type: 'callout', level: 'info', content: '' }) },
		{ type: 'quote', icon: 'mdi:format-quote-close', label: 'Quote', factory: () => ({ type: 'quote', text: '' }) },
		{ type: 'progress', icon: 'mdi:progress-check', label: 'Progress', factory: () => ({ type: 'progress', items: [{ label: 'Item', value: 50 }] }) },
		{ type: 'timeline', icon: 'mdi:timeline', label: 'Timeline', factory: () => ({ type: 'timeline', items: [{ title: 'Event' }] }) },
		{ type: 'divider', icon: 'mdi:minus', label: 'Divider', factory: () => ({ type: 'divider' }) },
	];
</script>

<div class="relative flex items-center my-0.5 group/insert">
	<div class="flex-1 h-px bg-border opacity-0 group-hover/insert:opacity-100 transition-opacity"></div>
	<button
		class="flex items-center justify-center w-5 h-5 rounded-full bg-muted border border-border text-muted-foreground hover:text-foreground hover:bg-card opacity-0 group-hover/insert:opacity-100 transition-all mx-1"
		onclick={() => (open = !open)}
		title="Insert block"
		aria-label="Insert block"
	>
		<Icon icon="mdi:plus" class="size-3" />
	</button>
	<div class="flex-1 h-px bg-border opacity-0 group-hover/insert:opacity-100 transition-opacity"></div>

	{#if open}
		<div
			class="fixed inset-0 z-40"
			onclick={() => (open = false)}
			onkeydown={handleKeydown}
			role="button"
			tabindex="-1"
		></div>
		<div class="absolute top-full left-1/2 -translate-x-1/2 z-50 mt-1 w-40 rounded-md border border-border bg-popover shadow-md py-1 max-h-80 overflow-y-auto">
			<p class="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Content</p>
			{#each contentBlocks as item (item.type)}
				<button
					class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
					onclick={() => insert(item.factory())}
				>
					<Icon icon={item.icon} class="size-3.5" />
					{item.label}
				</button>
			{/each}
			<div class="border-t border-border my-1"></div>
			<p class="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Visual</p>
			{#each visualBlocks as item (item.type)}
				<button
					class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
					onclick={() => insert(item.factory())}
				>
					<Icon icon={item.icon} class="size-3.5" />
					{item.label}
				</button>
			{/each}
		</div>
	{/if}
</div>
