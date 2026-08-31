<script lang="ts">
	import type { DividerBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: DividerBlockData;
		onUpdate: (data: DividerBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(false);

	$effect(() => {
		if (previewMode) isEditing = false;
	});

	const styleMap: Record<string, string> = {
		solid: 'border-solid',
		dashed: 'border-dashed',
		dotted: 'border-dotted',
	};

	let borderClass = $derived(styleMap[data.style ?? 'solid'] ?? 'border-solid');
</script>

{#if isEditing && !previewMode}
	<div class="p-4 flex items-center gap-3">
		<select class="select select-sm text-xs w-28" value={data.style ?? 'solid'} onchange={(e) => onUpdate({ ...data, style: e.currentTarget.value as DividerBlockData['style'] })}>
			<option value="solid">Solid</option>
			<option value="dashed">Dashed</option>
			<option value="dotted">Dotted</option>
		</select>
		<input class="input input-sm text-xs flex-1" placeholder="Label (optional)" value={data.label ?? ''} oninput={(e) => onUpdate({ ...data, label: e.currentTarget.value || undefined })} />
		<button class="text-xs text-muted-foreground hover:text-foreground" onclick={() => (isEditing = false)}>Done</button>
	</div>
{:else}
	<button
		class="w-full py-4 px-2"
		onclick={() => { if (!previewMode) isEditing = true; }}
		disabled={previewMode}
	>
		{#if data.label}
			<div class="flex items-center gap-3">
				<div class="flex-1 border-t {borderClass} border-border"></div>
				<span class="text-xs text-muted-foreground shrink-0">{data.label}</span>
				<div class="flex-1 border-t {borderClass} border-border"></div>
			</div>
		{:else}
			<div class="border-t {borderClass} border-border"></div>
		{/if}
	</button>
{/if}
