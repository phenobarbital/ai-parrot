<script lang="ts">
	import type { SummaryBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: SummaryBlockData;
		onUpdate: (data: SummaryBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(true);

	$effect(() => {
		if (previewMode) isEditing = false;
		else if (!data.content?.trim()) isEditing = true;
	});

	function renderContent(text: string): string {
		return text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
			.replace(/\*([^*]+)\*/g, '<em>$1</em>')
			.replace(/\n/g, '<br>');
	}
</script>

{#if isEditing && !previewMode}
	<div class="p-4 flex flex-col gap-2">
		<input
			class="input input-sm text-xs"
			placeholder="Section title (optional)"
			value={data.title ?? ''}
			oninput={(e) => onUpdate({ ...data, title: e.currentTarget.value || undefined })}
		/>
		<textarea
			class="textarea textarea-sm text-xs min-h-[80px]"
			placeholder="Summary content... (supports **bold** and *italic*)"
			value={data.content}
			oninput={(e) => onUpdate({ ...data, content: e.currentTarget.value })}
		></textarea>
		<div class="flex items-center gap-3">
			<label class="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
				<input
					type="checkbox"
					class="checkbox checkbox-xs"
					checked={data.highlight ?? false}
					onchange={(e) => onUpdate({ ...data, highlight: e.currentTarget.checked })}
				/>
				Highlight
			</label>
			<button class="text-xs text-muted-foreground hover:text-foreground" onclick={() => (isEditing = false)}>Preview</button>
		</div>
	</div>
{:else}
	<button
		class="w-full text-left"
		onclick={() => { if (!previewMode) isEditing = true; }}
		disabled={previewMode}
	>
		<div class="rounded-lg p-5 {data.highlight ? 'bg-primary/10 border-l-4 border-primary' : 'bg-card border border-border'}">
			{#if data.title}
				<h3 class="text-base font-semibold text-foreground mb-2">{data.title}</h3>
			{/if}
			{#if data.content?.trim()}
				<div class="text-sm text-foreground leading-relaxed">
					<!-- eslint-disable-next-line svelte/no-at-html-tags -->
					{@html renderContent(data.content)}
				</div>
			{:else}
				<p class="text-sm text-muted-foreground/40 italic">Write a summary...</p>
			{/if}
		</div>
	</button>
{/if}
