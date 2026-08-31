<script lang="ts">
	import type { TitleBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: TitleBlockData;
		onUpdate: (data: TitleBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(!previewMode);

	// React to previewMode prop changes — sync editing state with global toggle
	$effect(() => {
		if (previewMode) {
			isEditing = false;
		} else {
			// When preview mode is toggled off, restore editing if block has no content
			if (!data.title?.trim()) isEditing = true;
		}
	});

	function handleTitleInput(e: Event) {
		onUpdate({ title: (e.target as HTMLInputElement).value, subtitle: data.subtitle });
	}

	function handleSubtitleInput(e: Event) {
		onUpdate({ title: data.title, subtitle: (e.target as HTMLInputElement).value });
	}
</script>

<div class="px-4 py-3">
	{#if isEditing && !previewMode}
		<!-- Edit mode: plain text inputs -->
		<div class="flex flex-col gap-2">
			<input
				class="w-full bg-transparent text-2xl font-bold text-foreground border-0 border-b border-border focus:outline-none focus:border-primary placeholder:text-muted-foreground/50 pb-1"
				type="text"
				placeholder="Title"
				value={data.title}
				oninput={handleTitleInput}
			/>
			<input
				class="w-full bg-transparent text-xl text-muted-foreground border-0 border-b border-border/50 focus:outline-none focus:border-primary/50 placeholder:text-muted-foreground/30 pb-1"
				type="text"
				placeholder="Subtitle (optional)"
				value={data.subtitle ?? ''}
				oninput={handleSubtitleInput}
			/>
			<button
				class="self-start text-xs text-muted-foreground hover:text-foreground mt-1"
				onclick={() => (isEditing = false)}
			>
				Preview
			</button>
		</div>
	{:else}
		<!-- Preview mode: rendered headings -->
		<button
			class="w-full text-left"
			onclick={() => { if (!previewMode) isEditing = true; }}
			disabled={previewMode}
		>
			{#if data.title.trim()}
				<h1 class="text-2xl font-bold text-foreground mb-1">{data.title}</h1>
			{:else}
				<h1 class="text-2xl font-bold text-muted-foreground/40 italic mb-1">Title</h1>
			{/if}
			{#if data.subtitle?.trim()}
				<h2 class="text-xl text-muted-foreground">{data.subtitle}</h2>
			{/if}
		</button>
	{/if}
</div>
