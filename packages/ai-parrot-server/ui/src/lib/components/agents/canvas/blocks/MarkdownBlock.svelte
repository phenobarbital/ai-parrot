<script lang="ts">
	import { markdownToHtml } from '$lib/utils/markdown';
	import type { MarkdownBlockData } from '../canvas-block-types';
	import MarkdownToolbar from './MarkdownToolbar.svelte';

	let {
		data,
		blockId,
		onUpdate,
		previewMode = false
	}: {
		data: MarkdownBlockData;
		blockId: string;
		onUpdate: (data: MarkdownBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let mode = $state<'edit' | 'preview'>('edit');
	let isFocused = $state(false);
	let height = $state<number>(200);
	let isResizing = $state(false);

	let content = $derived(data.content);
	let textareaSelector = $derived(`.block-editor-${blockId}`);

	let renderedHtml = $derived(
		markdownToHtml(content, { allowHtml: true, allowSvg: true, allowImages: true })
	);

	// Sync block mode with global preview toggle
	$effect(() => {
		if (previewMode) {
			mode = 'preview';
		} else {
			mode = 'edit';
		}
	});

	function setContent(value: string) {
		onUpdate({ content: value });
	}

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

<div class="flex flex-col rounded-md overflow-visible border border-border" style="height: {height}px;">
	<!-- Toolbar: hidden in global preview mode -->
	{#if !previewMode}
		<div class="flex items-center gap-1 shrink-0 border-b border-border px-2 py-1 bg-muted/20">
			<!-- Edit/Preview toggle -->
			<div class="flex items-center rounded-md border border-border overflow-hidden text-xs">
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
			{#if mode === 'edit'}
				<MarkdownToolbar
					{textareaSelector}
					{content}
					onContentChange={setContent}
				/>
			{/if}
		</div>
	{/if}

	<!-- Content area: min-h-0 here + overflow-y-auto on the textarea avoids the double scrollbar that appears when both the wrapper and the textarea scroll independently -->
	<div class="flex-1 min-h-0">
		{#if mode === 'edit' && !previewMode}
			<textarea
				class={`block-editor-${blockId} w-full resize-none border-0 bg-transparent p-3 text-sm text-foreground focus:outline-none font-mono h-full overflow-y-auto`}
				value={content}
				oninput={(e) => setContent(e.currentTarget.value)}
				onfocus={() => (isFocused = true)}
				onblur={() => (isFocused = false)}
				placeholder="Write markdown here..."
			></textarea>
		{:else}
			<div
				class="p-3 canvas-prose max-w-none {!previewMode ? 'cursor-pointer' : ''} h-full overflow-y-auto"
				onclick={() => { if (!previewMode) mode = 'edit'; }}
				onkeydown={(e) => { if (!previewMode && e.key === 'Enter') mode = 'edit'; }}
				role="button"
				tabindex="0"
			>
				{#if content.trim()}
					{@html renderedHtml}
				{:else}
					<p class="text-muted-foreground italic text-sm">{previewMode ? 'Empty block.' : 'Empty block — click to edit.'}</p>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Resize handle - outside content area to avoid scrollbar overlap (hidden in preview mode) -->
	{#if !previewMode}
		<button
			class="absolute bottom-0 right-0 w-6 h-6 cursor-se-resize bg-gradient-to-tl from-primary/40 to-transparent hover:from-primary/60 border-t border-l border-primary/50 hover:border-primary transition-all"
			onmousedown={startResize}
			title="Drag to resize"
			aria-label="Resize block"
			style="transform: translate(0.5px, 0.5px); border-radius: 0 0 3px 0;"
		></button>
	{/if}
</div>
