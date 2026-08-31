<script lang="ts">
	import Icon from '@iconify/svelte';
	import * as tabManager from './canvas-tab-manager.svelte.js';
	import {
		createBlock,
		isCanvasBlockArray,
		migrateStringToBlocks,
		migrateChartArrayToBlocks
	} from './canvas-block-types';
	import type { CanvasBlock, CanvasBlockType } from './canvas-block-types';
	
	// Block sub-components
	import BlockToolbar from './blocks/BlockToolbar.svelte';
	import BlockInsertHandle from './blocks/BlockInsertHandle.svelte';
	import MarkdownBlock from './blocks/MarkdownBlock.svelte';
	import ChartBlock from './blocks/ChartBlock.svelte';
	import ImageBlock from './blocks/ImageBlock.svelte';
	import TableBlock from './blocks/TableBlock.svelte';
	import MapBlock from './blocks/MapBlock.svelte';
	import HtmlBlock from './blocks/HtmlBlock.svelte';
	import InteractiveBlock from './blocks/InteractiveBlock.svelte';
	import TitleBlock from './blocks/TitleBlock.svelte';
	import HeroCardBlock from './blocks/HeroCardBlock.svelte';
	import SummaryBlock from './blocks/SummaryBlock.svelte';
	import QuoteBlock from './blocks/QuoteBlock.svelte';
	import CalloutBlock from './blocks/CalloutBlock.svelte';
	import DividerBlock from './blocks/DividerBlock.svelte';
	import BulletListBlock from './blocks/BulletListBlock.svelte';

	let { data, previewMode = false }: { data: unknown; previewMode?: boolean } = $props();

	// Standalone mode: when data prop is explicitly a CanvasBlock[], use it directly
	// (e.g., ResultArea.svelte manages its own blocks outside the tab manager)
	let isStandalone = $derived(isCanvasBlockArray(data));

	// Read the active tab from the tab manager (single source of truth in managed mode)
	let activeTab = $derived(tabManager.getActiveTab());
	let isLoading = $derived(!isStandalone && activeTab?.data === '__loading__');

	// Standalone blocks state (used only in standalone mode)
	let standaloneBlocks = $state<CanvasBlock[]>([]);
	$effect(() => {
		if (isStandalone) standaloneBlocks = data as CanvasBlock[];
	});

	let emptyMenuOpen = $state(false);

	// Resolve blocks from tab data (managed mode) or prop (standalone mode)
	let blocks = $derived.by((): CanvasBlock[] => {
		if (isStandalone) return standaloneBlocks;
		const d = activeTab?.data;
		if (d === '__loading__') return [];
		if (isCanvasBlockArray(d)) return d;
		if (typeof d === 'string') {
			// Migrate old string format
			const migrated = migrateStringToBlocks(d);
			if (activeTab && migrated.length > 0) {
				// Persist migration (deferred to avoid reactivity loop)
				queueMicrotask(() => {
					tabManager.updateTabData(activeTab!.id, migrated);
				});
			}
			return migrated;
		}
		if (d !== null && typeof d === 'object' && 'charts' in (d as object)) {
			// Migrate old { charts: [] } format
			const migrated = migrateChartArrayToBlocks(d as { charts?: any[] });
			if (activeTab && migrated.length > 0) {
				queueMicrotask(() => {
					tabManager.updateTabData(activeTab!.id, migrated);
				});
			}
			return migrated;
		}
		return [];
	});

	// ─── Block CRUD ───────────────────────────────────────────────────────────────

	function persistBlocks(updated: CanvasBlock[]) {
		if (isStandalone) {
			standaloneBlocks = updated;
		} else if (activeTab) {
			tabManager.updateTabData(activeTab.id, updated);
		}
	}

	function addBlock(type: CanvasBlockType, blockData: CanvasBlock['data'], afterBlockId?: string) {
		const newBlock = createBlock(type, blockData);
		const current = [...blocks];
		if (afterBlockId) {
			const idx = current.findIndex((b) => b.id === afterBlockId);
			if (idx !== -1) {
				current.splice(idx + 1, 0, newBlock);
			} else {
				current.push(newBlock);
			}
		} else {
			current.push(newBlock);
		}
		persistBlocks(current);
	}

	function removeBlock(blockId: string) {
		persistBlocks(blocks.filter((b) => b.id !== blockId));
	}

	function moveBlockUp(blockId: string) {
		const current = [...blocks];
		const idx = current.findIndex((b) => b.id === blockId);
		if (idx > 0) {
			[current[idx - 1], current[idx]] = [current[idx], current[idx - 1]];
			persistBlocks(current);
		}
	}

	function moveBlockDown(blockId: string) {
		const current = [...blocks];
		const idx = current.findIndex((b) => b.id === blockId);
		if (idx !== -1 && idx < current.length - 1) {
			[current[idx], current[idx + 1]] = [current[idx + 1], current[idx]];
			persistBlocks(current);
		}
	}

	function updateBlockData(blockId: string, newData: CanvasBlock['data']) {
		persistBlocks(blocks.map((b) => (b.id === blockId ? { ...b, data: newData } : b)));
	}

</script>

<div class="flex flex-col h-full">
	{#if isLoading}
		<!-- Loading state -->
		<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3">
			<div class="animate-spin">
				<Icon icon="mdi:loading" class="size-8 opacity-60" />
			</div>
			<p class="text-sm font-medium">Generating content...</p>
		</div>
	{:else if blocks.length === 0}
		<!-- Empty state -->
		<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3">
			<Icon icon="mdi:note-outline" class="size-12 opacity-40" />
			<p class="text-sm font-medium">Start typing or add a block</p>
			<div class="relative">
				<button
					class="btn btn-outline btn-sm gap-2"
					onclick={() => (emptyMenuOpen = !emptyMenuOpen)}
				>
					<Icon icon="mdi:plus" class="size-4" />
					Add block
				</button>
				{#if emptyMenuOpen}
					<div
						class="fixed inset-0 z-40"
						onclick={() => (emptyMenuOpen = false)}
						onkeydown={(e) => e.key === 'Escape' && (emptyMenuOpen = false)}
						role="button"
						tabindex="-1"
					></div>
					<div class="absolute top-full left-1/2 -translate-x-1/2 z-50 mt-1 w-40 rounded-md border border-border bg-popover shadow-md py-1 max-h-72 overflow-y-auto">
						<p class="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Content</p>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('title', { title: '', subtitle: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:format-title" class="size-3.5" /> Title
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('markdown', { content: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:text" class="size-3.5" /> Markdown
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('summary', { content: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:text-box-outline" class="size-3.5" /> Summary
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('bullet_list', { items: [''] }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:format-list-bulleted" class="size-3.5" /> Bullet List
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('html', { html: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:code-tags" class="size-3.5" /> HTML
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('image', { url: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:image" class="size-3.5" /> Image
						</button>
						<div class="border-t border-border my-1"></div>
						<p class="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Visual</p>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('hero_card', { label: '', value: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:card-text-outline" class="size-3.5" /> KPI Card
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('callout', { level: 'info', content: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:alert-box-outline" class="size-3.5" /> Callout
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('quote', { text: '' }); emptyMenuOpen = false; }}>
							<Icon icon="mdi:format-quote-close" class="size-3.5" /> Quote
						</button>
						<button class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors" onclick={() => { addBlock('divider', {}); emptyMenuOpen = false; }}>
							<Icon icon="mdi:minus" class="size-3.5" /> Divider
						</button>
					</div>
				{/if}
			</div>
		</div>
	{:else}
		<!-- Blocks list -->
		<div class="flex-1 overflow-y-auto p-3 flex flex-col gap-1">
			<!-- Top insert handle -->
			<BlockInsertHandle onInsert={(type, blockData) => {
				if (blocks.length > 0) {
					// Insert before first block
					const current = [...blocks];
					const newBlock = createBlock(type, blockData);
					current.unshift(newBlock);
					persistBlocks(current);
				} else {
					addBlock(type, blockData);
				}
			}} />

			{#each blocks as block, i (block.id)}
				<div class="group relative rounded-lg border border-transparent hover:border-border transition-colors">
					<!-- Per-block toolbar (shown on hover) -->
					<BlockToolbar
						{block}
						index={i}
						total={blocks.length}
						onMoveUp={() => moveBlockUp(block.id)}
						onMoveDown={() => moveBlockDown(block.id)}
						onDelete={() => removeBlock(block.id)}
					/>

					<!-- Block content by type -->
					{#if block.type === 'markdown'}
						<MarkdownBlock
							data={block.data as import('./canvas-block-types').MarkdownBlockData}
							blockId={block.id}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'chart'}
						<ChartBlock
							data={block.data as import('./canvas-block-types').ChartBlockData}
							onDelete={() => removeBlock(block.id)}
						/>
					{:else if block.type === 'image'}
						<ImageBlock
							data={block.data as import('./canvas-block-types').ImageBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'table'}
						<TableBlock
							data={block.data as import('./canvas-block-types').TableBlockData}
						/>
					{:else if block.type === 'map'}
						<MapBlock
							data={block.data as import('./canvas-block-types').MapBlockData}
							onDelete={() => removeBlock(block.id)}
						/>
					{:else if block.type === 'html'}
						<HtmlBlock
							data={block.data as import('./canvas-block-types').HtmlBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'interactive'}
						<InteractiveBlock />
					{:else if block.type === 'title'}
						<TitleBlock
							data={block.data as import('./canvas-block-types').TitleBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'hero_card'}
						<HeroCardBlock
							data={block.data as import('./canvas-block-types').HeroCardBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'summary'}
						<SummaryBlock
							data={block.data as import('./canvas-block-types').SummaryBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'quote'}
						<QuoteBlock
							data={block.data as import('./canvas-block-types').QuoteBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'callout'}
						<CalloutBlock
							data={block.data as import('./canvas-block-types').CalloutBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'divider'}
						<DividerBlock
							data={block.data as import('./canvas-block-types').DividerBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{:else if block.type === 'bullet_list'}
						<BulletListBlock
							data={block.data as import('./canvas-block-types').BulletListBlockData}
							onUpdate={(newData) => updateBlockData(block.id, newData)}
							{previewMode}
						/>
					{/if}
				</div>

				<!-- Insert handle between blocks -->
				<BlockInsertHandle onInsert={(type, blockData) => addBlock(type, blockData, block.id)} />
			{/each}
		</div>
	{/if}
</div>
