<script lang="ts">
	import { markdownToHtml } from '$lib/utils/markdown';
	import Icon from '@iconify/svelte';
	import * as tabManager from './canvas-tab-manager.svelte.js';

	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	let { data }: { data: unknown } = $props();

	let mode = $state<'edit' | 'preview'>('edit');

	// Read content from tab manager (single source of truth)
	let activeTab = $derived(tabManager.getActiveTab());
	let rawContent = $derived((activeTab?.data as string) ?? '');
	let isLoading = $derived(rawContent === '__loading__');
	let content = $derived(isLoading ? '' : rawContent);
	let wasLoading = $state(false);

	// Auto-switch to preview when content arrives after loading
	$effect(() => {
		if (isLoading) {
			wasLoading = true;
		} else if (wasLoading && content.trim()) {
			mode = 'preview';
			wasLoading = false;
		}
	});

	let renderedHtml = $derived(
		markdownToHtml(content, { allowHtml: true, allowSvg: true, allowImages: true })
	);

	function setContent(value: string) {
		if (activeTab) {
			tabManager.updateTabData(activeTab.id, value);
		}
	}

	function insertAtCursor(before: string, after: string = '') {
		const textarea = document.querySelector<HTMLTextAreaElement>('.canvas-editor-textarea');
		if (!textarea) return;

		const start = textarea.selectionStart;
		const end = textarea.selectionEnd;
		const selected = content.slice(start, end);
		const replacement = before + (selected || 'text') + after;
		setContent(content.slice(0, start) + replacement + content.slice(end));

		// Restore cursor position after the inserted text
		requestAnimationFrame(() => {
			textarea.focus();
			const newPos = start + before.length + (selected || 'text').length;
			textarea.selectionStart = newPos;
			textarea.selectionEnd = newPos;
		});
	}

	function handleBold() { insertAtCursor('**', '**'); }
	function handleItalic() { insertAtCursor('*', '*'); }
	function handleStrikethrough() { insertAtCursor('~~', '~~'); }
	function handleH1() { insertAtCursor('# '); }
	function handleH2() { insertAtCursor('## '); }
	function handleH3() { insertAtCursor('### '); }
	function handleInlineCode() { insertAtCursor('`', '`'); }
	function handleCodeBlock() { insertAtCursor('```\n', '\n```'); }
	function handleUL() { insertAtCursor('- '); }
	function handleOL() { insertAtCursor('1. '); }
	function handleBlockquote() { insertAtCursor('> '); }
	function handleLink() { insertAtCursor('[', '](https://)'); }
</script>

<div class="flex flex-col h-full">
	{#if isLoading}
		<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3">
			<div class="animate-spin">
				<Icon icon="mdi:loading" class="size-8 opacity-60" />
			</div>
			<p class="text-sm font-medium">Generating content...</p>
		</div>
	{:else}
	<!-- Toolbar -->
	<div class="flex flex-col border-b border-border bg-muted/20 shrink-0">
		<div class="flex items-center px-2 py-1 gap-1">
			<!-- Mode toggle — pinned left, always visible -->
			<div class="flex items-center rounded-md border border-border overflow-hidden text-xs shrink-0">
				<button
					class="px-2.5 py-1 transition-colors {mode === 'edit' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (mode = 'edit')}
				>
					Edit
				</button>
				<button
					class="px-2.5 py-1 transition-colors {mode === 'preview' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (mode = 'preview')}
				>
					Preview
				</button>
			</div>

			<div class="w-px h-4 bg-border shrink-0"></div>

			<!-- Formatting buttons — scrollable if width is narrow -->
			<div class="flex items-center gap-0.5 overflow-x-auto min-w-0 flex-1">
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleBold} title="Bold" disabled={mode === 'preview'}>
					<Icon icon="mdi:format-bold" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleItalic} title="Italic" disabled={mode === 'preview'}>
					<Icon icon="mdi:format-italic" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleStrikethrough} title="Strikethrough" disabled={mode === 'preview'}>
					<Icon icon="mdi:format-strikethrough" class="size-4" />
				</button>

				<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

				<button class="btn btn-ghost btn-xs btn-square font-bold text-[11px] shrink-0" onclick={handleH1} title="Heading 1" disabled={mode === 'preview'}>H1</button>
				<button class="btn btn-ghost btn-xs btn-square font-bold text-[11px] shrink-0" onclick={handleH2} title="Heading 2" disabled={mode === 'preview'}>H2</button>
				<button class="btn btn-ghost btn-xs btn-square font-bold text-[11px] shrink-0" onclick={handleH3} title="Heading 3" disabled={mode === 'preview'}>H3</button>

				<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleUL} title="Unordered list" disabled={mode === 'preview'}>
					<Icon icon="mdi:format-list-bulleted" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleOL} title="Ordered list" disabled={mode === 'preview'}>
					<Icon icon="mdi:format-list-numbered" class="size-4" />
				</button>

				<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleInlineCode} title="Inline code" disabled={mode === 'preview'}>
					<Icon icon="mdi:code-tags" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleCodeBlock} title="Code block" disabled={mode === 'preview'}>
					<Icon icon="mdi:code-braces" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleBlockquote} title="Blockquote" disabled={mode === 'preview'}>
					<Icon icon="mdi:format-quote-open" class="size-4" />
				</button>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleLink} title="Link" disabled={mode === 'preview'}>
					<Icon icon="mdi:link" class="size-4" />
				</button>
			</div>
		</div>
	</div>

	<!-- Content Area -->
	<div class="flex-1 overflow-y-auto">
		{#if mode === 'edit'}
			<textarea
				class="canvas-editor-textarea w-full h-full resize-none border-0 bg-transparent p-4 text-sm text-foreground focus:outline-none font-mono"
				value={content}
				oninput={(e) => setContent(e.currentTarget.value)}
				placeholder="Write markdown here... Use the toolbar or type directly."
			></textarea>
		{:else}
			<div class="p-4 canvas-prose max-w-none">
				{#if content.trim()}
					{@html renderedHtml}
				{:else}
					<p class="text-muted-foreground italic">Nothing to preview yet.</p>
				{/if}
			</div>
		{/if}
	</div>
	{/if}
</div>
