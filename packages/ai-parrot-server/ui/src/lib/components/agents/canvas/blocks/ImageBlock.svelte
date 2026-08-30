<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { ImageBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: ImageBlockData;
		onUpdate: (data: ImageBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let mode = $state<'view' | 'edit'>('view');

	// Force view mode when global preview mode is active
	$effect(() => {
		if (previewMode) mode = 'view';
	});
	let imageError = $state(false);
	let urlInput = $state(data.url);
	let captionInput = $state(data.caption ?? '');
	let altInput = $state(data.alt ?? '');

	function handleSave() {
		onUpdate({ url: urlInput.trim(), alt: altInput.trim() || undefined, caption: captionInput.trim() || undefined });
		imageError = false;
		mode = 'view';
	}

	function handleImageError() {
		imageError = true;
	}

	function handleImageLoad() {
		imageError = false;
	}

	// Sync inputs when data changes
	$effect(() => {
		urlInput = data.url;
		captionInput = data.caption ?? '';
		altInput = data.alt ?? '';
	});
</script>

<div class="p-3 flex flex-col gap-2">
	{#if mode === 'view'}
		{#if !data.url}
			<!-- No URL set -->
			<div class="flex flex-col items-center justify-center p-6 border border-dashed border-border rounded-lg text-muted-foreground gap-2">
				<Icon icon="mdi:image-outline" class="size-8 opacity-50" />
				<p class="text-sm">No image URL set</p>
				<button class="btn btn-outline btn-xs" onclick={() => (mode = 'edit')}>Set URL</button>
			</div>
		{:else if imageError}
			<!-- Broken image placeholder -->
			<div class="flex flex-col items-center justify-center p-6 border border-dashed border-border rounded-lg text-muted-foreground gap-2">
				<Icon icon="mdi:image-broken" class="size-8 opacity-50" />
				<p class="text-sm">Image failed to load</p>
				<p class="text-xs text-muted-foreground/60 break-all max-w-full">{data.url}</p>
				<button class="btn btn-outline btn-xs" onclick={() => (mode = 'edit')}>Edit URL</button>
			</div>
		{:else}
			<!-- Image display -->
			<div class="flex flex-col gap-1">
				<img
					src={data.url}
					alt={data.alt || ''}
					class="max-w-full rounded-md"
					onerror={handleImageError}
					onload={handleImageLoad}
				/>
				{#if data.caption}
					<p class="text-xs text-muted-foreground italic text-center">{data.caption}</p>
				{/if}
				{#if !previewMode}
					<button
						class="btn btn-ghost btn-xs self-start text-muted-foreground"
						onclick={() => (mode = 'edit')}
					>
						<Icon icon="mdi:pencil" class="size-3.5" />
						Edit
					</button>
				{/if}
			</div>
		{/if}
	{:else}
		<!-- Edit mode -->
		<div class="flex flex-col gap-2">
			<div>
				<label class="text-xs font-medium text-foreground mb-1 block">Image URL</label>
				<input
					class="input input-sm w-full"
					type="url"
					placeholder="https://example.com/image.png"
					bind:value={urlInput}
				/>
			</div>
			<div>
				<label class="text-xs font-medium text-foreground mb-1 block">Alt text</label>
				<input
					class="input input-sm w-full"
					type="text"
					placeholder="Description of the image"
					bind:value={altInput}
				/>
			</div>
			<div>
				<label class="text-xs font-medium text-foreground mb-1 block">Caption (optional)</label>
				<input
					class="input input-sm w-full"
					type="text"
					placeholder="Caption shown below image"
					bind:value={captionInput}
				/>
			</div>
			<div class="flex gap-2">
				<button class="btn btn-primary btn-sm" onclick={handleSave}>Save</button>
				<button class="btn btn-ghost btn-sm" onclick={() => (mode = 'view')}>Cancel</button>
			</div>
		</div>
	{/if}
</div>
