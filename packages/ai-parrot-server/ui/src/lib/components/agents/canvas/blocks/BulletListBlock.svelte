<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { BulletListBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: BulletListBlockData;
		onUpdate: (data: BulletListBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(true);

	$effect(() => {
		if (previewMode) isEditing = false;
		else if (!data.items.length || !data.items.some(i => i.trim())) isEditing = true;
	});

	function updateItem(index: number, value: string) {
		const items = [...data.items];
		items[index] = value;
		onUpdate({ ...data, items });
	}

	function addItem() {
		onUpdate({ ...data, items: [...data.items, ''] });
	}

	function removeItem(index: number) {
		const items = data.items.filter((_, i) => i !== index);
		onUpdate({ ...data, items: items.length ? items : [''] });
	}

	function handleKeydown(e: KeyboardEvent, index: number) {
		if (e.key === 'Enter') {
			e.preventDefault();
			const items = [...data.items];
			items.splice(index + 1, 0, '');
			onUpdate({ ...data, items });
			// Focus will be handled by Svelte re-render
		} else if (e.key === 'Backspace' && data.items[index] === '' && data.items.length > 1) {
			e.preventDefault();
			removeItem(index);
		}
	}
</script>

{#if isEditing && !previewMode}
	<div class="p-4 flex flex-col gap-2">
		<div class="flex items-center gap-2 mb-1">
			<input class="input input-sm text-xs flex-1" placeholder="List title (optional)" value={data.title ?? ''} oninput={(e) => onUpdate({ ...data, title: e.currentTarget.value || undefined })} />
			<label class="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer shrink-0">
				<input
					type="checkbox"
					class="checkbox checkbox-xs"
					checked={data.ordered ?? false}
					onchange={(e) => onUpdate({ ...data, ordered: e.currentTarget.checked })}
				/>
				Numbered
			</label>
		</div>
		{#each data.items as item, i (i)}
			<div class="flex items-center gap-1.5">
				<span class="text-xs text-muted-foreground w-4 text-right shrink-0">{data.ordered ? `${i + 1}.` : '•'}</span>
				<input
					class="input input-sm text-xs flex-1"
					placeholder="List item..."
					value={item}
					oninput={(e) => updateItem(i, e.currentTarget.value)}
					onkeydown={(e) => handleKeydown(e, i)}
				/>
				<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={() => removeItem(i)} title="Remove item">
					<Icon icon="mdi:close" class="size-3" />
				</button>
			</div>
		{/each}
		<div class="flex gap-2">
			<button class="btn btn-ghost btn-xs gap-1" onclick={addItem}>
				<Icon icon="mdi:plus" class="size-3" /> Add item
			</button>
			<button class="text-xs text-muted-foreground hover:text-foreground" onclick={() => (isEditing = false)}>Preview</button>
		</div>
	</div>
{:else}
	<button
		class="w-full text-left"
		onclick={() => { if (!previewMode) isEditing = true; }}
		disabled={previewMode}
	>
		<div class="p-4">
			{#if data.title}
				<h3 class="text-sm font-semibold text-foreground mb-2">{data.title}</h3>
			{/if}
			{#if data.ordered}
				<ol class="list-decimal list-inside text-sm text-foreground space-y-1">
					{#each data.items.filter(i => i.trim()) as item, i (i)}
						<li>{item}</li>
					{/each}
				</ol>
			{:else}
				<ul class="list-disc list-inside text-sm text-foreground space-y-1">
					{#each data.items.filter(i => i.trim()) as item, i (i)}
						<li>{item}</li>
					{/each}
				</ul>
			{/if}
			{#if !data.items.some(i => i.trim())}
				<p class="text-sm text-muted-foreground/40 italic">Add list items...</p>
			{/if}
		</div>
	</button>
{/if}
