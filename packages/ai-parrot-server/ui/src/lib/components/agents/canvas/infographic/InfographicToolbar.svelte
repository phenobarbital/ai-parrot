<script lang="ts">
	import Icon from '@iconify/svelte';
	import { onMount } from 'svelte';
	import { fetchTemplates, fetchThemes, generateInfographicFromApi } from '$lib/api/infographic';
	import type {
		InfographicData,
		TemplateItem,
		ThemeItem
	} from './infographic-types';

	interface GenerateResultJson {
		mode: 'json';
		data: InfographicData;
	}
	interface GenerateResultHtml {
		mode: 'html';
		html: string;
	}
	type GenerateResult = GenerateResultJson | GenerateResultHtml;

	interface Props {
		agentId: string;
		query?: string;
		template?: string;
		theme?: string;
		onGenerate: (result: GenerateResult) => void;
		onError: (message: string) => void;
	}

	let {
		agentId,
		query: initialQuery = '',
		template: initialTemplate = 'basic',
		theme: initialTheme = 'light',
		onGenerate,
		onError
	}: Props = $props();

	// ─── State ──────────────────────────────────────────────────────────────────

	let query = $state(initialQuery);
	let selectedTemplate = $state(initialTemplate);
	let selectedTheme = $state(initialTheme);
	let format = $state<'json' | 'html'>('json');

	let extraContext = $state('');
	let showExtraContext = $state(false);

	let templates = $state<(string | TemplateItem)[]>([]);
	let themes = $state<(string | ThemeItem)[]>([]);
	let loadingMeta = $state(true);
	let generating = $state(false);

	let canCreate = $derived(query.trim().length > 0 && !generating);

	// ─── Load templates/themes once ─────────────────────────────────────────────

	let metaLoaded = false;

	async function loadMeta() {
		if (metaLoaded) return;
		metaLoaded = true;
		loadingMeta = true;
		try {
			const [tplRes, thmRes] = await Promise.all([fetchTemplates(true), fetchThemes(true)]);
			templates = tplRes.templates;
			themes = thmRes.themes;
		} catch {
			// Fallback to built-in catalog if API unavailable
			templates = ['basic', 'comparison', 'dashboard', 'executive', 'minimal', 'timeline'];
			themes = ['light', 'corporate', 'dark'];
		} finally {
			loadingMeta = false;
		}
	}

	// Load on first render (client-side only to avoid SSR network requests)
	onMount(() => loadMeta());

	// ─── Helpers ─────────────────────────────────────────────────────────────────

	function getTemplateName(t: string | TemplateItem): string {
		return typeof t === 'string' ? t : t.name;
	}

	function getTemplateDescription(t: string | TemplateItem): string {
		return typeof t === 'string' ? '' : (t.description ?? '');
	}

	function getThemeName(t: string | ThemeItem): string {
		return typeof t === 'string' ? t : t.name;
	}

	function getThemePrimary(t: string | ThemeItem): string | undefined {
		return typeof t === 'string' ? undefined : t.primary;
	}

	// ─── Generate ────────────────────────────────────────────────────────────────

	async function handleCreate() {
		if (!canCreate) return;
		generating = true;
		try {
			const fullQuery = extraContext.trim()
				? query.trim() + '\n\nAdditional context: ' + extraContext.trim()
				: query.trim();
			const result = await generateInfographicFromApi(
				agentId,
				{ query: fullQuery, template: selectedTemplate, theme: selectedTheme },
				format
			);

			if (format === 'json' && typeof result === 'object' && 'infographic' in result) {
				const infographic = result.infographic;
				if (!infographic || !Array.isArray(infographic.blocks)) {
					onError('The API returned an infographic without valid blocks.');
					return;
				}
				onGenerate({ mode: 'json', data: infographic });
			} else if (format === 'html' && typeof result === 'string') {
				onGenerate({ mode: 'html', html: result });
			} else {
				onError('Unexpected response format from infographic API.');
			}
		} catch (err: unknown) {
			const msg = err instanceof Error ? err.message : 'Infographic generation failed.';
			onError(msg);
		} finally {
			generating = false;
		}
	}
</script>

<div class="border-b border-border bg-muted/20 shrink-0">
	<!-- Row 1: controls -->
	<div class="flex flex-wrap items-center gap-2 px-3 py-2">
		<!-- Template picker -->
		<div class="flex items-center gap-1.5 min-w-0">
			<Icon icon="mdi:file-document-outline" class="size-3.5 text-muted-foreground shrink-0" />
			{#if loadingMeta}
				<div class="select w-28 h-6 bg-muted animate-pulse rounded text-xs"></div>
			{:else}
				<select
					class="select select-sm text-xs py-0 h-6 min-h-0"
					bind:value={selectedTemplate}
					title="Template"
					aria-label="Template"
				>
					{#each templates as tpl}
						{@const name = getTemplateName(tpl)}
						{@const desc = getTemplateDescription(tpl)}
						<option value={name} title={desc}>{name}</option>
					{/each}
				</select>
			{/if}
		</div>

		<!-- Theme picker -->
		<div class="flex items-center gap-1.5 min-w-0">
			<Icon icon="mdi:palette" class="size-3.5 text-muted-foreground shrink-0" />
			{#if loadingMeta}
				<div class="select w-24 h-6 bg-muted animate-pulse rounded text-xs"></div>
			{:else}
				<select
					class="select select-sm text-xs py-0 h-6 min-h-0"
					bind:value={selectedTheme}
					title="Theme"
					aria-label="Theme"
				>
					{#each themes as thm}
						{@const name = getThemeName(thm)}
						{@const primary = getThemePrimary(thm)}
						<option value={name}>
							{#if primary}
								■
							{/if}
							{name}
						</option>
					{/each}
				</select>
			{/if}
		</div>

		<!-- Mode toggle -->
		<div class="flex items-center gap-1.5 shrink-0">
			<span class="text-xs text-muted-foreground">Mode:</span>
			<div class="flex items-center rounded-md border border-border overflow-hidden text-xs">
				<button
					class="px-2 py-0.5 transition-colors {format === 'json' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (format = 'json')}
					title="Native block rendering"
				>
					Visual Blocks
				</button>
				<button
					class="px-2 py-0.5 transition-colors {format === 'html' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (format = 'html')}
					title="HTML document rendering"
				>
					HTML
				</button>
			</div>
		</div>

		<!-- Toggle extra context -->
		<button
			class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground shrink-0"
			class:text-primary={showExtraContext}
			onclick={() => (showExtraContext = !showExtraContext)}
			title={showExtraContext ? 'Hide extra context' : 'Add extra context'}
		>
			<Icon icon="mdi:text-box-plus-outline" class="size-3.5" />
		</button>

		<!-- Create button -->
		<button
			class="btn btn-sm btn-primary text-xs gap-1 h-6 min-h-0 shrink-0"
			onclick={handleCreate}
			disabled={!canCreate}
			title="Generate infographic"
		>
			{#if generating}
				<Icon icon="mdi:loading" class="size-3.5 animate-spin" />
				Generating…
			{:else}
				<Icon icon="mdi:creation" class="size-3.5" />
				Create
			{/if}
		</button>
	</div>

	<!-- Row 2: extra context (collapsible) -->
	{#if showExtraContext}
		<div class="flex items-center gap-2 px-3 pb-2">
			<label for="extra-context" class="text-xs text-muted-foreground whitespace-nowrap shrink-0">
				Extra Context:
			</label>
			<input
				id="extra-context"
				type="text"
				class="input input-sm text-xs h-6 min-h-0 flex-1"
				placeholder="e.g. focus on revenue trends, include competitor comparison…"
				bind:value={extraContext}
				aria-label="Additional context"
			/>
		</div>
	{/if}
</div>
