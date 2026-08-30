<script lang="ts">
	import Icon from '@iconify/svelte';
	import { v4 as uuidv4 } from 'uuid';
	import * as tabManager from './canvas-tab-manager.svelte.js';
	import { getCanvasComponent } from './canvas-registry.js';
	import type { CanvasTabType } from './canvas-tab-manager.svelte.js';
	import { serializeBlocksForInfographic } from '$lib/api/infographic';
	import { generateSpeechReport } from '$lib/api/speechReport';
	import { toastStore } from '$lib/stores/toast.svelte';
	import * as chatLayout from '$lib/stores/agentchat-layout.svelte';
	import {
		isCanvasBlockArray,
		createBlock
	} from './canvas-block-types';
	import type { CanvasBlock, MarkdownBlockData, ChartBlockData, TableBlockData, TitleBlockData, SummaryBlockData, QuoteBlockData, CalloutBlockData, BulletListBlockData, HeroCardBlockData } from './canvas-block-types';
	import {
		exportBlocksToHtml,
		exportAllTabsToHtml,
		downloadHtml,
		printHtml
	} from './canvas-block-exporter';

	let { onClose, agentId = '' }: { onClose: () => void; agentId?: string } = $props();
	let generatingAudio = $state(false);
	let exportMenuOpen = $state(false);

	let expanded = $derived(chatLayout.getCanvasExpanded());

	/** Serialize CanvasBlock[] to text for audio generation */
	function serializeBlocksToText(blocks: CanvasBlock[]): string {
		return blocks
			.map((block) => {
				if (block.type === 'markdown') return (block.data as MarkdownBlockData).content;
				if (block.type === 'chart') {
					const d = block.data as ChartBlockData;
					return `[Chart: ${d.config.title || 'Untitled'}]\n${JSON.stringify(d.data)}`;
				}
				if (block.type === 'table') {
					return `[Table]\n${JSON.stringify((block.data as TableBlockData).rows)}`;
				}
				if (block.type === 'title') {
					const d = block.data as TitleBlockData;
					return [d.title, d.subtitle].filter(Boolean).join('\n');
				}
				if (block.type === 'summary') {
					const d = block.data as SummaryBlockData;
					return [d.title, d.content].filter(Boolean).join('\n');
				}
				if (block.type === 'quote') {
					const d = block.data as QuoteBlockData;
					return `"${d.text}"${d.author ? ` — ${d.author}` : ''}`;
				}
				if (block.type === 'callout') {
					const d = block.data as CalloutBlockData;
					return [d.title, d.content].filter(Boolean).join(': ');
				}
				if (block.type === 'bullet_list') {
					const d = block.data as BulletListBlockData;
					const header = d.title ? `${d.title}\n` : '';
					return header + d.items.filter(i => i.trim()).map(i => `• ${i}`).join('\n');
				}
				if (block.type === 'hero_card') {
					const d = block.data as HeroCardBlockData;
					return `${d.label}: ${d.value}`;
				}
				return '';
			})
			.filter(Boolean)
			.join('\n\n---\n\n');
	}

	function handleCreateInfographic() {
		// Gather main canvas content to use as query context
		const mainTab = tabManager.getTabs().find((t) => t.id === 'main-canvas');
		const blocks = isCanvasBlockArray(mainTab?.data) ? (mainTab!.data as CanvasBlock[]) : [];
		const content = serializeBlocksForInfographic(blocks);

		// Open an empty infographic tab — toolbar inside InfographicCanvas handles generation
		tabManager.addTab('infographic', 'Infographic', {
			mode: 'json',
			query: content || '',
			template: 'basic',
			theme: 'light'
		});
	}

	async function handleListenThis() {
		if (!agentId) {
			toastStore.info('No agent selected — cannot generate audio report.');
			return;
		}

		const mainTab = tabManager.getTabs().find((t) => t.id === 'main-canvas');
		const blocks = isCanvasBlockArray(mainTab?.data) ? (mainTab!.data as CanvasBlock[]) : [];
		const content = serializeBlocksToText(blocks);

		if (!content.trim()) {
			toastStore.info('Main Canvas is empty — add some content first.');
			return;
		}

		const tabId = tabManager.addTab('audio', 'Audio Report', '__loading__');
		generatingAudio = true;

		try {
			const result = await generateSpeechReport(agentId, content);
			tabManager.updateTabData(tabId, {
				podcastPath: result.podcast_path,
				scriptPath: result.script_path
			});
		} catch (err: any) {
			tabManager.updateTabData(tabId, null);
			toastStore.error(`Audio report failed: ${err?.message || 'Unknown error'}`);
		} finally {
			generatingAudio = false;
		}
	}

	/** Create a new empty Block Canvas tab */
	function handleNewCanvas() {
		const count = tabManager.getTabs().filter((t) => t.type === 'markdown' && t.closable).length;
		tabManager.addTab('markdown', `Canvas ${count + 1}`, []);
	}

	/** Duplicate the active tab's blocks into a new tab */
	function handleDuplicateCanvas() {
		const activeTab = tabManager.getActiveTab();
		if (!activeTab) return;

		if (isCanvasBlockArray(activeTab.data)) {
			// Deep clone blocks and assign new UUIDs
			const cloned = JSON.parse(JSON.stringify(activeTab.data)) as CanvasBlock[];
			cloned.forEach((block) => { block.id = uuidv4(); });
			tabManager.addTab(activeTab.type, `${activeTab.title} (copy)`, cloned);
		} else if (activeTab.type === 'spreadsheet') {
			// Convert spreadsheet data to a table block
			const rows = Array.isArray(activeTab.data) ? (activeTab.data as Record<string, unknown>[]) : [];
			const tableBlock = createBlock('table', { rows });
			tabManager.addTab('markdown', `${activeTab.title} (copy)`, [tableBlock]);
		} else {
			toastStore.info('Cannot duplicate this tab type.');
		}
	}

	/** Export handlers */
	function handleExportHtml() {
		const tab = tabManager.getActiveTab();
		if (!tab) { toastStore.info('No active tab to export.'); exportMenuOpen = false; return; }
		const blocks = isCanvasBlockArray(tab.data) ? (tab.data as CanvasBlock[]) : [];
		const html = exportBlocksToHtml(blocks, tab.title);
		downloadHtml(html, `${tab.title.replace(/\s+/g, '-')}.html`);
		exportMenuOpen = false;
		toastStore.success('Canvas exported as HTML.');
	}

	function handlePrint() {
		const tab = tabManager.getActiveTab();
		if (!tab) { toastStore.info('No active tab to print.'); exportMenuOpen = false; return; }
		const blocks = isCanvasBlockArray(tab.data) ? (tab.data as CanvasBlock[]) : [];
		const html = exportBlocksToHtml(blocks, tab.title);
		printHtml(html);
		exportMenuOpen = false;
	}

	function handleExportAll() {
		const allTabs = tabManager.getTabs();
		const html = exportAllTabsToHtml(allTabs);
		downloadHtml(html, 'canvas-all-tabs.html');
		exportMenuOpen = false;
		toastStore.success('All canvas tabs exported.');
	}

	// Initialize main canvas tab on first render
	tabManager.initCanvas();

	let tabs = $derived(tabManager.getTabs());
	let activeTabId = $derived(tabManager.getActiveTabId());
	let activeTab = $derived(tabManager.getActiveTab());
	let ActiveComponent = $derived(activeTab ? getCanvasComponent(activeTab.type) : undefined);

	// Add-tab menu state
	let addMenuOpen = $state(false);

	// Global preview mode — per-tab, resets when switching tabs
	let previewMode = $state(false);
	$effect(() => {
		activeTabId; // reactive dependency — reset preview mode on tab switch
		previewMode = false;
	});

	// Note: 'interactive' tabs are intentionally excluded from this list — they
	// are only meaningful when auto-opened by the agent (which populates them with
	// artifact data). A manually-created interactive tab would always be empty.
	const tabTypes: { type: CanvasTabType; label: string; icon: string }[] = [
		{ type: 'markdown', label: 'Markdown', icon: 'mdi:language-markdown' },
		{ type: 'chart', label: 'Chart', icon: 'mdi:chart-bar' },
		{ type: 'spreadsheet', label: 'Spreadsheet', icon: 'mdi:table-large' },
		{ type: 'infographic', label: 'Infographic', icon: 'mdi:image-text' },
		{ type: 'audio', label: 'Audio', icon: 'mdi:headphones' },
	];

	function handleAddTab(type: CanvasTabType, label: string) {
		if (type === 'infographic') {
			const mainTab = tabManager.getTabs().find((t) => t.id === 'main-canvas');
			const blocks = isCanvasBlockArray(mainTab?.data) ? (mainTab!.data as CanvasBlock[]) : [];
			const content = serializeBlocksForInfographic(blocks);
			tabManager.addTab(type, label, { mode: 'json', query: content || '' });
		} else {
			tabManager.addTab(type, label, type === 'markdown' || type === 'chart' ? [] : null);
		}
		addMenuOpen = false;
	}

	function iconForType(type: CanvasTabType): string {
		return tabTypes.find((t) => t.type === type)?.icon ?? 'mdi:file-outline';
	}
</script>

<div class="flex flex-col h-full">
	<!-- Header -->
	<div class="flex items-center justify-between px-3 h-8 border-b border-border shrink-0">
		<h3 class="font-bold text-[13px] text-foreground">Canvas</h3>
		<div class="flex items-center gap-1">
			<!-- New Canvas -->
			<button
				class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
				onclick={handleNewCanvas}
				title="New Canvas"
			>
				<Icon icon="mdi:plus-box-outline" class="size-3.5" />
			</button>

			<!-- Duplicate Canvas -->
			<button
				class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
				onclick={handleDuplicateCanvas}
				title="Duplicate Canvas"
			>
				<Icon icon="mdi:content-copy" class="size-3.5" />
			</button>

			<!-- Export dropdown -->
			<div class="relative">
				<button
					class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
					onclick={() => (exportMenuOpen = !exportMenuOpen)}
					title="Export"
				>
					<Icon icon="mdi:export-variant" class="size-3.5" />
				</button>

				{#if exportMenuOpen}
					<!-- Backdrop -->
					<div
						class="fixed inset-0 z-40"
						onclick={() => (exportMenuOpen = false)}
						onkeydown={(e) => e.key === 'Escape' && (exportMenuOpen = false)}
						role="button"
						tabindex="-1"
					></div>
					<!-- Dropdown -->
					<div class="absolute top-full right-0 z-50 mt-1 w-44 rounded-md border border-border bg-popover shadow-md py-1">
						<button
							class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
							onclick={handleExportHtml}
						>
							<Icon icon="mdi:file-code-outline" class="size-3.5" />
							Export as HTML
						</button>
						<button
							class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
							onclick={handlePrint}
						>
							<Icon icon="mdi:printer-outline" class="size-3.5" />
							Print / PDF
						</button>
						<button
							class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
							onclick={handleExportAll}
						>
							<Icon icon="mdi:archive-export-outline" class="size-3.5" />
							Export All
						</button>
					</div>
				{/if}
			</div>

			<button
				class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
				onclick={handleCreateInfographic}
				title="Create Infographic"
			>
				<Icon icon="mdi:image-text" class="size-3.5" />
				<span class="text-[11px]">Infographic</span>
			</button>
			<button
				class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
				onclick={handleListenThis}
				disabled={generatingAudio}
				title="Listen This"
			>
				{#if generatingAudio}
					<Icon icon="mdi:loading" class="size-3.5 animate-spin" />
				{:else}
					<Icon icon="mdi:headphones" class="size-3.5" />
				{/if}
			</button>
			<!-- Edit/Preview toggle — only for block canvas tabs -->
			{#if activeTab && (activeTab.type === 'markdown' || activeTab.type === 'chart')}
				<div class="flex items-center rounded-md border border-border overflow-hidden text-xs mx-1">
					<button
						class="px-2 py-0.5 transition-colors {!previewMode ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
						onclick={() => (previewMode = false)}
						title="Edit mode"
					>
						Edit
					</button>
					<button
						class="px-2 py-0.5 transition-colors {previewMode ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
						onclick={() => (previewMode = true)}
						title="Preview mode"
					>
						Preview
					</button>
				</div>
			{/if}
			<button
				class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
				onclick={() => chatLayout.toggleCanvasExpanded()}
				title={expanded ? 'Restore chat' : 'Expand canvas'}
				aria-label={expanded ? 'Restore chat' : 'Expand canvas'}
			>
				<Icon icon={expanded ? 'mdi:arrow-collapse-right' : 'mdi:arrow-expand-left'} class="size-4" />
			</button>
			<button
				class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
				onclick={onClose}
				title="Close Canvas"
				aria-label="Close Canvas"
			>
				<Icon icon="mdi:close" class="size-4" />
			</button>
		</div>
	</div>

	<!-- Tab Bar -->
	<div class="flex items-center border-b border-border bg-muted/30 shrink-0">
		<div class="flex items-center overflow-x-auto flex-1">
			{#each tabs as tab (tab.id)}
				<div
					class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border-r border-border whitespace-nowrap transition-colors cursor-pointer
						{tab.id === activeTabId
						? 'bg-card text-foreground border-b-2 border-b-primary'
						: 'text-muted-foreground hover:text-foreground hover:bg-muted/50'}"
					onclick={() => tabManager.setActiveTab(tab.id)}
					onkeydown={(e) => e.key === 'Enter' && tabManager.setActiveTab(tab.id)}
					role="tab"
					tabindex="0"
					aria-selected={tab.id === activeTabId}
				>
					<Icon icon={iconForType(tab.type)} class="size-3.5" />
					<span>{tab.title}</span>
					{#if tab.closable}
						<button
							class="ml-1 rounded-sm hover:bg-muted p-0.5"
							onclick={(e: MouseEvent) => { e.stopPropagation(); tabManager.removeTab(tab.id); }}
							aria-label="Close tab {tab.title}"
						>
							<Icon icon="mdi:close" class="size-3" />
						</button>
					{/if}
				</div>
			{/each}
		</div>

		<!-- Add Tab Button (outside overflow container so dropdown isn't clipped) -->
		<div class="relative shrink-0">
			<button
				class="flex items-center justify-center px-2 py-1.5 text-muted-foreground hover:text-foreground transition-colors"
				onclick={() => (addMenuOpen = !addMenuOpen)}
				aria-label="Add tab"
			>
				<Icon icon="mdi:plus" class="size-4" />
			</button>

			{#if addMenuOpen}
				<!-- Backdrop -->
				<div
					class="fixed inset-0 z-40"
					onclick={() => (addMenuOpen = false)}
					onkeydown={(e) => e.key === 'Escape' && (addMenuOpen = false)}
					role="button"
					tabindex="-1"
				></div>
				<!-- Dropdown -->
				<div
					class="absolute top-full right-0 z-50 mt-1 w-40 rounded-md border border-border bg-popover shadow-md py-1"
				>
					{#each tabTypes as tt}
						<button
							class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
							onclick={(e) => { e.stopPropagation(); handleAddTab(tt.type, tt.label); }}
						>
							<Icon icon={tt.icon} class="size-3.5" />
							{tt.label}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<!-- Tab Content -->
	<div class="flex-1 overflow-y-auto">
		{#if activeTab}
			{#if ActiveComponent}
				<ActiveComponent data={activeTab.data} {previewMode} {agentId} />
			{:else}
				<!-- Placeholder for unregistered tab types -->
				<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6">
					<Icon icon={iconForType(activeTab.type)} class="size-12 mb-3 opacity-40" />
					<p class="text-sm font-medium">{activeTab.title}</p>
					<p class="text-xs mt-1">This canvas type will be available soon.</p>
				</div>
			{/if}
		{:else}
			<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6">
				<Icon icon="mdi:palette-outline" class="size-12 mb-3 opacity-40" />
				<p class="text-sm font-medium">Canvas</p>
				<p class="text-xs mt-1">Open a tab to get started.</p>
			</div>
		{/if}
	</div>
</div>
