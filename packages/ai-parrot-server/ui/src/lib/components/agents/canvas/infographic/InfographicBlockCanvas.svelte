<script lang="ts">
	import Icon from '@iconify/svelte';
	import { getInfographicBlock } from './infographic-registry';
	import type { InfographicData, InfographicBlock } from './infographic-types';
	import InfographicInsertHandle from './InfographicInsertHandle.svelte';

	interface Props {
		infographic: InfographicData;
		onBlocksChange?: (blocks: InfographicBlock[]) => void;
	}

	let { infographic, onBlocksChange }: Props = $props();

	// Local copy of blocks for reordering (doesn't mutate the prop)
	let blocks = $state<InfographicBlock[]>([...(infographic.blocks ?? [])]);

	// Keep in sync if infographic prop changes (e.g. user regenerates).
	let selfUpdate = false;

	$effect(() => {
		const incoming = infographic.blocks ?? [];
		if (selfUpdate) {
			selfUpdate = false;
			return;
		}
		blocks = [...incoming];
	});

	// Notify parent whenever blocks are modified (add, remove, reorder)
	function notifyChange() {
		selfUpdate = true;
		onBlocksChange?.(blocks);
	}

	function moveBlockUp(index: number) {
		if (index <= 0) return;
		const copy = [...blocks];
		[copy[index - 1], copy[index]] = [copy[index], copy[index - 1]];
		blocks = copy;
		notifyChange();
	}

	function moveBlockDown(index: number) {
		if (index >= blocks.length - 1) return;
		const copy = [...blocks];
		[copy[index], copy[index + 1]] = [copy[index + 1], copy[index]];
		blocks = copy;
		notifyChange();
	}

	function removeBlock(index: number) {
		blocks = blocks.filter((_, i) => i !== index);
		notifyChange();
	}

	function insertBlockAt(index: number, block: InfographicBlock) {
		const copy = [...blocks];
		copy.splice(index, 0, block);
		blocks = copy;
		notifyChange();
	}

	function appendBlock(block: InfographicBlock) {
		blocks = [...blocks, block];
		notifyChange();
	}

	type GroupKind = 'hero' | 'chart-row';
	type GroupedEntry =
		| { group: true; kind: GroupKind; blocks: InfographicBlock[]; startIndex: number }
		| { group: false; block: InfographicBlock; index: number };

	/**
	 * Group consecutive blocks for side-by-side rendering:
	 *   - hero_card runs → row of cards
	 *   - chart blocks with layout:'half' runs → 2-column chart row
	 * Anything else renders as a single full-width block.
	 */
	function groupConsecutiveBlocks(blockList: InfographicBlock[]): GroupedEntry[] {
		const result: GroupedEntry[] = [];
		let i = 0;
		const isHalfChart = (b: InfographicBlock) =>
			b.type === 'chart' && (b as InfographicBlock & { layout?: string }).layout === 'half';
		while (i < blockList.length) {
			if (blockList[i].type === 'hero_card') {
				const start = i;
				const heroGroup: InfographicBlock[] = [];
				while (i < blockList.length && blockList[i].type === 'hero_card') {
					heroGroup.push(blockList[i]);
					i++;
				}
				result.push({ group: true, kind: 'hero', blocks: heroGroup, startIndex: start });
			} else if (isHalfChart(blockList[i])) {
				const start = i;
				const chartGroup: InfographicBlock[] = [];
				while (i < blockList.length && isHalfChart(blockList[i])) {
					chartGroup.push(blockList[i]);
					i++;
				}
				// Singleton half-chart still renders as a row (for visual consistency).
				result.push({ group: true, kind: 'chart-row', blocks: chartGroup, startIndex: start });
			} else {
				result.push({ group: false, block: blockList[i], index: i });
				i++;
			}
		}
		return result;
	}

	let grouped = $derived(groupConsecutiveBlocks(blocks));
</script>

<div class="flex flex-col gap-6 p-4">
	<!-- Top insert handle -->
	<InfographicInsertHandle onInsert={(block) => insertBlockAt(0, block)} />

	{#each grouped as entry, entryIdx (entryIdx)}
		{#if entry.group}
			<!-- Grouped row: hero cards (auto N cols) or half-charts (2 cols) -->
			<div
				class={entry.kind === 'chart-row'
					? 'grid grid-cols-1 md:grid-cols-2 gap-4'
					: 'grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4'}
			>
				{#each entry.blocks as heroBlock, heroIdx (`${entry.kind}-${entry.startIndex}-${heroIdx}`)}
					{@const globalIdx = entry.startIndex + heroIdx}
					{@const BlockComponent = getInfographicBlock(heroBlock.type)}
					<div class="group relative">
						{#if BlockComponent}
							<BlockComponent {...heroBlock} />
						{:else}
							<div class="rounded-lg border border-dashed border-border bg-muted/20 p-4 text-center text-xs text-muted-foreground">
								[{heroBlock.type}]
							</div>
						{/if}
						<!-- Reorder + delete buttons (shown on hover) -->
						<div class="absolute top-1 right-1 hidden group-hover:flex flex-col gap-0.5 bg-background/80 backdrop-blur-sm rounded border border-border shadow-sm p-0.5">
							<button
								class="p-0.5 rounded hover:bg-muted disabled:opacity-30"
								onclick={() => moveBlockUp(globalIdx)}
								disabled={globalIdx === 0}
								title="Move up"
								aria-label="Move block up"
							>
								<Icon icon="mdi:chevron-up" class="size-3" />
							</button>
							<button
								class="p-0.5 rounded hover:bg-muted disabled:opacity-30"
								onclick={() => moveBlockDown(globalIdx)}
								disabled={globalIdx === blocks.length - 1}
								title="Move down"
								aria-label="Move block down"
							>
								<Icon icon="mdi:chevron-down" class="size-3" />
							</button>
							<div class="border-t border-border"></div>
							<button
								class="p-0.5 rounded hover:bg-destructive/10 text-destructive/70 hover:text-destructive"
								onclick={() => removeBlock(globalIdx)}
								title="Remove block"
								aria-label="Remove block"
							>
								<Icon icon="mdi:trash-can-outline" class="size-3" />
							</button>
						</div>
					</div>
				{/each}
			</div>

			<!-- Insert handle after hero group -->
			<InfographicInsertHandle onInsert={(block) => insertBlockAt(entry.startIndex + entry.blocks.length, block)} />
		{:else}
			<!-- Single block -->
			{@const BlockComponent = getInfographicBlock(entry.block.type)}
			<div class="group relative">
				{#if BlockComponent}
					<BlockComponent {...entry.block} />
				{:else}
					<!-- Fallback placeholder for unregistered block types -->
					<div class="rounded-lg border border-dashed border-border bg-muted/20 p-4 text-center text-sm text-muted-foreground">
						<Icon icon="mdi:block-helper" class="size-5 mb-1 opacity-50" />
						<p>Block type <code class="bg-muted px-1 rounded text-xs">{entry.block.type}</code> is not registered.</p>
					</div>
				{/if}
				<!-- Reorder + delete buttons (shown on hover) -->
				<div class="absolute top-2 right-2 hidden group-hover:flex gap-0.5 bg-background/80 backdrop-blur-sm rounded border border-border shadow-sm p-0.5">
					<button
						class="p-0.5 rounded hover:bg-muted disabled:opacity-30"
						onclick={() => moveBlockUp(entry.index)}
						disabled={entry.index === 0}
						title="Move block up"
						aria-label="Move block up"
					>
						<Icon icon="mdi:arrow-up" class="size-3.5" />
					</button>
					<button
						class="p-0.5 rounded hover:bg-muted disabled:opacity-30"
						onclick={() => moveBlockDown(entry.index)}
						disabled={entry.index === blocks.length - 1}
						title="Move block down"
						aria-label="Move block down"
					>
						<Icon icon="mdi:arrow-down" class="size-3.5" />
					</button>
					<div class="border-l border-border mx-0.5"></div>
					<button
						class="p-0.5 rounded hover:bg-destructive/10 text-destructive/70 hover:text-destructive"
						onclick={() => removeBlock(entry.index)}
						title="Remove block"
						aria-label="Remove block"
					>
						<Icon icon="mdi:trash-can-outline" class="size-3.5" />
					</button>
				</div>
			</div>

			<!-- Insert handle after each block -->
			<InfographicInsertHandle onInsert={(block) => insertBlockAt(entry.index + 1, block)} />
		{/if}
	{/each}

	{#if blocks.length === 0}
		<!-- Empty state -->
		<div class="flex flex-col items-center justify-center py-16 text-center text-muted-foreground/60 gap-3">
			<Icon icon="mdi:view-dashboard-outline" class="size-12 opacity-40" />
			<p class="text-sm font-medium">No blocks yet</p>
			<p class="text-xs">Use the <span class="font-mono">+</span> handle above to add your first block</p>
		</div>
	{/if}
</div>
