<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { QuoteBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: QuoteBlockData;
		onUpdate: (data: QuoteBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(true);

	$effect(() => {
		if (previewMode) isEditing = false;
		else if (!data.text?.trim()) isEditing = true;
	});
</script>

{#if isEditing && !previewMode}
	<div class="p-4 flex flex-col gap-2">
		<textarea
			class="textarea textarea-sm text-xs min-h-[60px]"
			placeholder="Quote text..."
			value={data.text}
			oninput={(e) => onUpdate({ ...data, text: e.currentTarget.value })}
		></textarea>
		<div class="grid grid-cols-2 gap-2">
			<input class="input input-sm text-xs" placeholder="Author (optional)" value={data.author ?? ''} oninput={(e) => onUpdate({ ...data, author: e.currentTarget.value || undefined })} />
			<input class="input input-sm text-xs" placeholder="Source (optional)" value={data.source ?? ''} oninput={(e) => onUpdate({ ...data, source: e.currentTarget.value || undefined })} />
		</div>
		<button class="self-start text-xs text-muted-foreground hover:text-foreground" onclick={() => (isEditing = false)}>Preview</button>
	</div>
{:else}
	<button
		class="w-full text-left"
		onclick={() => { if (!previewMode) isEditing = true; }}
		disabled={previewMode}
	>
		<div class="border-l-4 border-primary/60 bg-muted/30 rounded-r-lg p-5">
			<Icon icon="mdi:format-quote-open" class="size-6 text-primary/40 mb-1" />
			{#if data.text?.trim()}
				<p class="text-sm italic text-foreground leading-relaxed">{data.text}</p>
			{:else}
				<p class="text-sm italic text-muted-foreground/40">Write a quote...</p>
			{/if}
			{#if data.author || data.source}
				<p class="text-xs text-muted-foreground mt-2">
					{#if data.author}— {data.author}{/if}
					{#if data.source}<span class="ml-1 opacity-70">({data.source})</span>{/if}
				</p>
			{/if}
		</div>
	</button>
{/if}
