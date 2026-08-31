<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { CanvasBlockType, CanvasBlock } from '../canvas-block-types';

	let {
		onInsert
	}: {
		onInsert: (type: CanvasBlockType, data: CanvasBlock['data']) => void;
	} = $props();

	let open = $state(false);
	let imageUrlInput = $state('');
	let showImagePrompt = $state(false);

	function handleInsertTitle() {
		onInsert('title', { title: '', subtitle: '' });
		open = false;
	}

	function handleInsertMarkdown() {
		onInsert('markdown', { content: '' });
		open = false;
	}

	function handleInsertHtml() {
		onInsert('html', { html: '' });
		open = false;
	}

	function handleInsertImageConfirm() {
		if (imageUrlInput.trim()) {
			onInsert('image', { url: imageUrlInput.trim() });
		}
		imageUrlInput = '';
		showImagePrompt = false;
		open = false;
	}

	function handleImageOption() {
		showImagePrompt = true;
		open = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			open = false;
			showImagePrompt = false;
		}
	}
</script>

<div class="relative flex items-center my-1 group/insert">
	<!-- Horizontal line with centered + button -->
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

	<!-- Dropdown -->
	{#if open}
		<!-- Backdrop -->
		<div
			class="fixed inset-0 z-40"
			onclick={() => (open = false)}
			onkeydown={handleKeydown}
			role="button"
			tabindex="-1"
		></div>
		<!-- Menu -->
		<div class="absolute top-full left-1/2 -translate-x-1/2 z-50 mt-1 w-40 rounded-md border border-border bg-popover shadow-md py-1 max-h-72 overflow-y-auto">
			<p class="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Content</p>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={handleInsertTitle}
			>
				<Icon icon="mdi:format-title" class="size-3.5" />
				Title
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={handleInsertMarkdown}
			>
				<Icon icon="mdi:text" class="size-3.5" />
				Markdown
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={() => { onInsert('summary', { content: '' }); open = false; }}
			>
				<Icon icon="mdi:text-box-outline" class="size-3.5" />
				Summary
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={() => { onInsert('bullet_list', { items: [''] }); open = false; }}
			>
				<Icon icon="mdi:format-list-bulleted" class="size-3.5" />
				Bullet List
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={handleInsertHtml}
			>
				<Icon icon="mdi:code-tags" class="size-3.5" />
				HTML
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={handleImageOption}
			>
				<Icon icon="mdi:image" class="size-3.5" />
				Image
			</button>
			<div class="border-t border-border my-1"></div>
			<p class="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Visual</p>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={() => { onInsert('hero_card', { label: '', value: '' }); open = false; }}
			>
				<Icon icon="mdi:card-text-outline" class="size-3.5" />
				KPI Card
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={() => { onInsert('callout', { level: 'info', content: '' }); open = false; }}
			>
				<Icon icon="mdi:alert-box-outline" class="size-3.5" />
				Callout
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={() => { onInsert('quote', { text: '' }); open = false; }}
			>
				<Icon icon="mdi:format-quote-close" class="size-3.5" />
				Quote
			</button>
			<button
				class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
				onclick={() => { onInsert('divider', {}); open = false; }}
			>
				<Icon icon="mdi:minus" class="size-3.5" />
				Divider
			</button>
		</div>
	{/if}

	<!-- Image URL prompt -->
	{#if showImagePrompt}
		<!-- Backdrop -->
		<div
			class="fixed inset-0 z-40 bg-black/20"
			onclick={() => (showImagePrompt = false)}
			onkeydown={handleKeydown}
			role="button"
			tabindex="-1"
		></div>
		<div class="absolute top-full left-1/2 -translate-x-1/2 z-50 mt-1 w-64 rounded-md border border-border bg-popover shadow-md p-3">
			<p class="text-xs font-medium text-foreground mb-2">Image URL</p>
			<input
				class="input input-sm w-full mb-2"
				type="url"
				placeholder="https://example.com/image.png"
				bind:value={imageUrlInput}
				onkeydown={(e) => e.key === 'Enter' && handleInsertImageConfirm()}
			/>
			<div class="flex gap-2 justify-end">
				<button class="btn btn-ghost btn-xs" onclick={() => (showImagePrompt = false)}>Cancel</button>
				<button class="btn btn-primary btn-xs" onclick={handleInsertImageConfirm}>Add</button>
			</div>
		</div>
	{/if}
</div>
