<script lang="ts">
	import type { HtmlBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: HtmlBlockData;
		onUpdate: (data: HtmlBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let mode = $state<'preview' | 'edit'>('preview');
	let height = $state<number>(300);
	let isResizing = $state(false);

	// Force preview when global preview mode is active
	$effect(() => {
		if (previewMode) mode = 'preview';
	});

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

<div class="flex flex-col rounded-md overflow-visible border border-border relative" style="height: {height}px;">
	<!-- Mode toggle — hidden in global preview mode -->
	{#if !previewMode}
		<div class="flex items-center gap-1 px-2 py-1 border-b border-border bg-muted/20 shrink-0">
			<div class="flex items-center rounded-md border border-border overflow-hidden text-xs">
				<button
					class="px-2.5 py-1 transition-colors {mode === 'preview' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (mode = 'preview')}
				>
					Preview
				</button>
				<button
					class="px-2.5 py-1 transition-colors {mode === 'edit' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'}"
					onclick={() => (mode = 'edit')}
				>
					Edit HTML
				</button>
			</div>
		</div>
	{/if}

	<div class="flex-1 overflow-hidden">
		{#if mode === 'edit' && !previewMode}
			<textarea
				class="w-full h-full resize-none font-mono text-xs p-3 bg-muted/10 focus:outline-none text-foreground"
				value={data.html}
				oninput={(e) => onUpdate({ html: e.currentTarget.value })}
				placeholder="Enter HTML content..."
			></textarea>
		{:else}
			{#if data.html.trim()}
				<iframe
					class="w-full h-full border-0"
					srcdoc={data.html}
					sandbox="allow-same-origin allow-modals"
					title="HTML block preview"
				></iframe>
			{:else}
				<div class="flex items-center justify-center text-muted-foreground text-sm p-4 h-full">
					<p>{previewMode ? 'Empty HTML block.' : 'No HTML content — click "Edit HTML" to add content.'}</p>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Resize handle - outside content area (hidden in preview mode) -->
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
