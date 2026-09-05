<script lang="ts">
	import { browser } from '$app/environment';
	import Icon from '@iconify/svelte';
	import * as tabManager from './canvas-tab-manager.svelte.js';
	// ai-parrot (FEAT-476 TASK-2595): InfographicEditor pulls in @tiptap/*
	// unconditionally — gated behind features.richEditor (spec §3 Module 5
	// "gate cross-surface imports"); falls back to the same plain
	// `<textarea>` HTML-source view used for `editView === 'code'` when
	// the flag is off (mirrors AppTextEditor's own richEditor fallback).
	import { features } from '$lib/features';
	import InfographicToolbar from './infographic/InfographicToolbar.svelte';
	import InfographicBlockCanvas from './infographic/InfographicBlockCanvas.svelte';
	import type { InfographicTabData, InfographicData, InfographicBlock } from './infographic/infographic-types';
	import { exportBlocksToHtml, collectChartImages } from './infographic/infographic-html-export';
	import { FINANCIAL_VARIANCE_DEMO } from './infographic/demo-financial-variance';
	// FEAT-527: A2UISurface reuses the SAME infographic block renderers
	// (Chart/DataTable/Timeline) InfographicBlockCanvas above already pulls
	// in statically — not a new heavy dependency — so it is imported the
	// same way and gated in markup only (`{#if features.a2ui}`), never
	// mounted/evaluated when the flag is off.
	import A2UISurface from './a2ui/A2UISurface.svelte';

	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	let { data, agentId = '' }: { data: unknown; agentId?: string } = $props();

	// Read content from tab manager (single source of truth)
	let activeTab = $derived(tabManager.getActiveTab());

	/**
	 * Normalize incoming tab data to InfographicTabData.
	 * Handles both legacy string format (HTML from FEAT-034) and new structured format (FEAT-039).
	 */
	function normalizeInfographicData(raw: unknown): InfographicTabData | null {
		if (!raw) return null;
		// Legacy: plain string HTML
		if (typeof raw === 'string') {
			if (raw === '__loading__') return null; // handled by isLoading
			return { mode: 'html', html: raw };
		}
		// New structured format
		if (typeof raw === 'object') {
			return raw as InfographicTabData;
		}
		return null;
	}

	let rawData = $derived(activeTab?.data);
	let isLoading = $derived(rawData === '__loading__');
	let tabData = $derived(normalizeInfographicData(rawData));

	// Derived content flags
	let hasHtml = $derived(
		tabData?.mode === 'html' && typeof tabData.html === 'string' && tabData.html.length > 0
	);
	let hasUrl = $derived(
		tabData?.mode === 'html' && typeof tabData.url === 'string' && tabData.url.length > 0
	);
	let hasJson = $derived(tabData?.mode === 'json' && tabData?.infographic != null);
	// FEAT-527: an a2ui tab additionally carries url/html so the toolbar's
	// Rendered/HTML toggle can still fall back to the iframe view.
	let hasA2ui = $derived(tabData?.mode === 'a2ui' && !!tabData.envelope);
	let a2uiHasHtmlFallback = $derived(
		hasA2ui && (typeof tabData?.html === 'string' ? tabData.html.length > 0 : !!tabData?.url),
	);
	let isEmpty = $derived(!isLoading && !hasHtml && !hasUrl && !hasJson && !hasA2ui);

	// Mode toggle state for the HTML editor
	let mode = $state<'edit' | 'preview'>('preview');
	let editView = $state<'code' | 'visual'>('visual');
	// FEAT-527: Rendered (A2UISurface) vs HTML (iframe) toggle for an a2ui tab.
	let a2uiView = $state<'rendered' | 'html'>('rendered');

	let iframeEl = $state<HTMLIFrameElement | null>(null);
	let blockCanvasEl = $state<HTMLDivElement | null>(null);

	function setHtmlContent(value: string) {
		if (activeTab) {
			const updated: InfographicTabData = {
				...(tabData ?? { mode: 'html' }),
				mode: 'html',
				html: value
			};
			tabManager.updateTabData(activeTab.id, updated);
		}
	}

	let printIframeEl = $state<HTMLIFrameElement | null>(null);

	/**
	 * Persist block changes (add, remove, reorder) back to the tab data
	 * so exports and prints always reflect the current state.
	 */
	function handleBlocksChange(updatedBlocks: InfographicBlock[]) {
		if (!activeTab || !tabData?.infographic) return;
		const updated: InfographicTabData = {
			...tabData,
			infographic: {
				...tabData.infographic,
				blocks: updatedBlocks
			}
		};
		tabManager.updateTabData(activeTab.id, updated);
	}

	/**
	 * Build a self-contained HTML document from the visual blocks data.
	 * Charts are captured as base64 PNG images from the live ECharts canvases.
	 */
	function buildExportHtml(): string {
		const blocks = tabData?.infographic?.blocks ?? [];
		const chartImages = blockCanvasEl ? collectChartImages(blockCanvasEl, blocks) : new Map<number, string>();
		return exportBlocksToHtml(blocks, chartImages);
	}

	function handleSave() {
		if (!browser) return;
		// FEAT-527: an a2ui tab has no local HTML export path — when there is
		// no inline html sibling artifact, fall back to opening the signed
		// backend-rendered url directly (the button is hidden entirely when
		// neither is present, see `a2uiHasHtmlFallback`).
		if (hasA2ui && typeof tabData?.html !== 'string') {
			if (tabData?.url) window.open(tabData.url, '_blank', 'noopener,noreferrer');
			return;
		}
		let html: string;
		if (hasJson) {
			html = buildExportHtml();
		} else {
			html = tabData?.html ?? '';
		}
		const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `infographic-${Date.now()}.html`;
		a.click();
		URL.revokeObjectURL(url);
	}

	function handlePrint() {
		if (!browser) return;
		if (hasJson) {
			// Write the export HTML into a hidden iframe and trigger print from it.
			// This avoids popup blockers and reliably opens the print dialog.
			const html = buildExportHtml();
			if (printIframeEl) {
				const doc = printIframeEl.contentDocument ?? printIframeEl.contentWindow?.document;
				if (doc) {
					doc.open();
					doc.write(html);
					doc.close();
					// Wait for content (especially images) to load before printing
					printIframeEl.onload = () => {
						printIframeEl?.contentWindow?.print();
					};
					// Fallback: if onload doesn't fire (already loaded), trigger after a short delay
					setTimeout(() => {
						printIframeEl?.contentWindow?.print();
					}, 500);
				}
			}
		} else if (iframeEl?.contentWindow) {
			iframeEl.contentWindow.print();
		}
	}

	function handleIframeLoad() {
		// no-op: iframe scrolls its own content via h-full
	}

	function handleGenerate(
		result: { mode: 'json'; data: InfographicData } | { mode: 'html'; html: string }
	) {
		if (!activeTab) return;
		let newData: InfographicTabData;

		if (result.mode === 'json') {
			newData = {
				mode: 'json',
				infographic: result.data,
				query: tabData?.query,
				template: tabData?.template,
				theme: tabData?.theme
			};
		} else {
			newData = {
				mode: 'html',
				html: result.html,
				query: tabData?.query,
				template: tabData?.template,
				theme: tabData?.theme
			};
		}
		tabManager.updateTabData(activeTab.id, newData);
	}

	let errorMessage = $state<string | null>(null);

	function handleError(message: string) {
		errorMessage = message;
	}

	function loadDemo() {
		// Deep-clone so the user can edit blocks without mutating the shared fixture.
		const data: InfographicData = JSON.parse(JSON.stringify(FINANCIAL_VARIANCE_DEMO));
		handleGenerate({ mode: 'json', data });
	}

	// Clear error when new data arrives
	$effect(() => {
		if (hasJson || hasHtml) {
			errorMessage = null;
		}
	});
</script>

<div class="flex flex-col h-full">
	{#if isLoading}
		<!-- Loading state (legacy __loading__ sentinel) -->
		<div
			class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3"
		>
			<div class="animate-spin">
				<Icon icon="mdi:loading" class="size-8 opacity-60" />
			</div>
			<p class="text-sm font-medium">Generating infographic...</p>
			<p class="text-xs">The agent is creating a visual summary of your data.</p>
		</div>
	{:else if isEmpty}
		<!-- Empty / setup state: show toolbar for user to configure and create -->
		<InfographicToolbar
			{agentId}
			query={tabData?.query ?? ''}
			template={tabData?.template ?? 'basic'}
			theme={tabData?.theme ?? 'light'}
			onGenerate={handleGenerate}
			onError={handleError}
		/>
		{#if errorMessage}
			<div
				class="mx-4 mt-3 rounded-md bg-destructive/10 border border-destructive/30 px-4 py-2 text-sm text-destructive flex items-start gap-2"
			>
				<Icon icon="mdi:alert-circle-outline" class="size-4 mt-0.5 shrink-0" />
				<span>{errorMessage}</span>
			</div>
		{/if}
		<div
			class="flex flex-col items-center justify-center flex-1 text-center text-muted-foreground/60 p-6 gap-3"
		>
			<Icon icon="mdi:image-text" class="size-12 mb-1 opacity-30" />
			<p class="text-sm font-medium">Configure your infographic above</p>
			<p class="text-xs">
				Select a template and theme, then click <strong>Create</strong>.
			</p>
			<div class="flex items-center gap-2 text-xs text-muted-foreground/70 mt-2">
				<span class="h-px w-8 bg-border"></span>
				<span>or</span>
				<span class="h-px w-8 bg-border"></span>
			</div>
			<button class="btn btn-ghost btn-sm gap-2 text-xs" onclick={loadDemo} title="Load the Financial Projection Variance demo">
				<Icon icon="mdi:lightning-bolt-outline" class="size-3.5" />
				Load demo: Financial Projection Variance
			</button>
		</div>
	{:else if hasJson}
		<!-- Visual Blocks mode: native block rendering -->
		<InfographicToolbar
			{agentId}
			query={tabData?.query ?? ''}
			template={tabData?.template ?? 'basic'}
			theme={tabData?.theme ?? 'light'}
			onGenerate={handleGenerate}
			onError={handleError}
		/>
		{#if errorMessage}
			<div
				class="mx-4 mt-2 rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2 text-xs text-destructive flex items-start gap-2"
			>
				<Icon icon="mdi:alert-circle-outline" class="size-3.5 mt-0.5 shrink-0" />
				<span>{errorMessage}</span>
			</div>
		{/if}
		<div class="flex-1 overflow-y-auto relative">
			<div bind:this={blockCanvasEl}>
				<InfographicBlockCanvas infographic={tabData!.infographic!} onBlocksChange={handleBlocksChange} />
			</div>
			<div
				class="absolute top-2 right-2 flex items-center gap-1 bg-background/80 backdrop-blur-sm border border-border rounded-md px-1 py-1 shadow-sm"
			>
				<button class="btn btn-ghost btn-xs btn-square" onclick={handleSave} title="Save as HTML">
					<Icon icon="mdi:download" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square" onclick={handlePrint} title="Print">
					<Icon icon="mdi:printer" class="size-4" />
				</button>
			</div>
			<!-- Hidden iframe for print — avoids popup blockers -->
			<iframe
				bind:this={printIframeEl}
				title="Print"
				class="absolute w-0 h-0 border-0 overflow-hidden"
				style="position:absolute;left:-9999px;"
			></iframe>
		</div>
	{:else if hasA2ui}
		<!-- FEAT-527: A2UI mode — Rendered (A2UISurface) / HTML (iframe) toggle. -->
		<div class="relative h-full flex flex-col">
			<div class="flex items-center px-2 py-1 gap-2 border-b border-border bg-muted/20 shrink-0">
				<div class="flex items-center rounded-md border border-border overflow-hidden text-xs shrink-0">
					<button
						class="px-2.5 py-1 transition-colors {a2uiView === 'rendered'
							? 'bg-primary text-primary-foreground'
							: 'hover:bg-muted text-muted-foreground'}"
						onclick={() => (a2uiView = 'rendered')}
					>
						Rendered
					</button>
					<button
						class="px-2.5 py-1 transition-colors disabled:opacity-40 disabled:cursor-not-allowed {a2uiView ===
						'html'
							? 'bg-primary text-primary-foreground'
							: 'hover:bg-muted text-muted-foreground'}"
						onclick={() => (a2uiView = 'html')}
						disabled={!a2uiHasHtmlFallback}
						title={a2uiHasHtmlFallback ? '' : 'No HTML artifact available'}
					>
						HTML
					</button>
				</div>
				<!-- FEAT-527: no A2UI->HTML export in the SPA — Save as HTML only
				     works when an HTML sibling artifact (inline html or a signed
				     url) exists on the tab; hidden otherwise (canvas-block-exporter
				     operates on markdown-canvas blocks, not a2ui envelopes). -->
				{#if a2uiHasHtmlFallback}
					<button class="btn btn-ghost btn-xs btn-square" onclick={handleSave} title="Save as HTML">
						<Icon icon="mdi:download" class="size-4" />
					</button>
				{/if}
			</div>
			<div class="flex-1 min-h-0 overflow-auto">
				{#if a2uiView === 'rendered' && features.a2ui}
					<A2UISurface envelope={tabData.envelope} />
				{:else if typeof tabData?.html === 'string' && tabData.html.length > 0}
					<!-- FEAT-527 code-review fix: srcdoc content must NOT carry
					     allow-same-origin — combined with allow-scripts it would let
					     the framed (agent/LLM-produced) HTML script inherit this
					     page's own origin (srcdoc normally gets a null/opaque origin,
					     which allow-same-origin defeats). Matches the safe pattern
					     already used for the "Preview mode" srcdoc iframe below. -->
					<iframe
						bind:this={iframeEl}
						srcdoc={tabData.html}
						sandbox="allow-scripts allow-modals allow-popups"
						title="Infographic"
						class="w-full h-full border-0"
						onload={handleIframeLoad}
					></iframe>
				{:else if tabData?.url}
					<iframe
						bind:this={iframeEl}
						src={tabData.url}
						sandbox="allow-scripts allow-same-origin allow-modals allow-popups"
						title="Infographic"
						class="w-full h-full border-0"
						onload={handleIframeLoad}
					></iframe>
				{:else}
					<div class="p-4 text-sm text-muted-foreground italic">
						A2UI rendering is disabled in this build.
					</div>
				{/if}
			</div>
		</div>
	{:else if hasUrl}
		<!-- URL mode: backend-rendered artifact loaded directly into an iframe -->
		<div class="relative h-full">
			<iframe
				bind:this={iframeEl}
				src={tabData?.url}
				sandbox="allow-scripts allow-same-origin allow-modals allow-popups"
				title="Infographic"
				class="w-full h-full border-0"
				onload={handleIframeLoad}
			></iframe>
			<div
				class="absolute top-2 right-2 flex items-center gap-1 bg-background/80 backdrop-blur-sm border border-border rounded-md px-1 py-1 shadow-sm"
			>
				<a
					class="btn btn-ghost btn-xs btn-square"
					href={tabData?.url}
					target="_blank"
					rel="noopener noreferrer"
					title="Open in new tab"
				>
					<Icon icon="mdi:open-in-new" class="size-4" />
				</a>
			</div>
		</div>
	{:else if hasHtml}
		<!-- HTML mode: toolbar + iframe -->
		<InfographicToolbar
			{agentId}
			query={tabData?.query ?? ''}
			template={tabData?.template ?? 'basic'}
			theme={tabData?.theme ?? 'light'}
			onGenerate={handleGenerate}
			onError={handleError}
		/>
		{#if errorMessage}
			<div
				class="mx-4 mt-2 rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2 text-xs text-destructive flex items-start gap-2"
			>
				<Icon icon="mdi:alert-circle-outline" class="size-3.5 mt-0.5 shrink-0" />
				<span>{errorMessage}</span>
			</div>
		{/if}
		<!-- Edit / Preview toggle bar -->
		<div class="flex items-center px-2 py-1 gap-2 border-b border-border bg-muted/20 shrink-0">
			<div class="flex items-center rounded-md border border-border overflow-hidden text-xs shrink-0">
				<button
					class="px-2.5 py-1 transition-colors {mode === 'edit'
						? 'bg-primary text-primary-foreground'
						: 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (mode = 'edit')}
				>
					Edit
				</button>
				<button
					class="px-2.5 py-1 transition-colors {mode === 'preview'
						? 'bg-primary text-primary-foreground'
						: 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (mode = 'preview')}
				>
					Preview
				</button>
			</div>

			{#if mode === 'edit'}
				<div class="w-px h-4 bg-border shrink-0"></div>
				<div class="flex items-center rounded-md border border-border overflow-hidden text-xs shrink-0">
					<button
						class="px-2 py-1 transition-colors {editView === 'code'
							? 'bg-muted text-foreground'
							: 'hover:bg-muted/50 text-muted-foreground'}"
						onclick={() => (editView = 'code')}
					>
						Code
					</button>
					<button
						class="px-2 py-1 transition-colors {editView === 'visual'
							? 'bg-muted text-foreground'
							: 'hover:bg-muted/50 text-muted-foreground'}"
						onclick={() => (editView = 'visual')}
					>
						Visual
					</button>
				</div>
			{/if}
		</div>

		<!-- Content Area -->
		<div class="flex-1 overflow-hidden">
			{#if mode === 'edit'}
				{#if editView === 'code'}
					<textarea
						class="w-full h-full resize-none border-0 bg-slate-900 text-slate-100 p-4 text-sm focus:outline-none font-mono"
						value={tabData?.html ?? ''}
						oninput={(e) => setHtmlContent(e.currentTarget.value)}
						placeholder="HTML source code..."
					></textarea>
				{:else if features.richEditor}
					{#await import('./InfographicEditor.svelte') then { default: InfographicEditor }}
						<InfographicEditor content={tabData?.html ?? ''} onUpdate={setHtmlContent} />
					{/await}
				{:else}
					<textarea
						class="w-full h-full resize-none border-0 bg-slate-900 text-slate-100 p-4 text-sm focus:outline-none font-mono"
						value={tabData?.html ?? ''}
						oninput={(e) => setHtmlContent(e.currentTarget.value)}
						placeholder="HTML source code..."
					></textarea>
				{/if}
			{:else}
				<!-- Preview mode: sandboxed iframe + floating action bar -->
				<div class="relative h-full">
					<iframe
						bind:this={iframeEl}
						srcdoc={tabData?.html ?? ''}
						sandbox="allow-scripts allow-modals"
						title="Infographic"
						class="w-full h-full border-0"
						onload={handleIframeLoad}
					></iframe>
					<div
						class="absolute top-2 right-2 flex items-center gap-1 bg-background/80 backdrop-blur-sm border border-border rounded-md px-1 py-1 shadow-sm"
					>
						<button class="btn btn-ghost btn-xs btn-square" onclick={handleSave} title="Save as HTML">
							<Icon icon="mdi:download" class="size-4" />
						</button>
						<button class="btn btn-ghost btn-xs btn-square" onclick={handlePrint} title="Print">
							<Icon icon="mdi:printer" class="size-4" />
						</button>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
