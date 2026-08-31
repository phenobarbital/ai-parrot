<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { CanvasBlock } from '../canvas-block-types';

	let {
		block,
		index,
		total,
		onMoveUp,
		onMoveDown,
		onDelete
	}: {
		block: CanvasBlock;
		index: number;
		total: number;
		onMoveUp: () => void;
		onMoveDown: () => void;
		onDelete: () => void;
	} = $props();

	function iconForType(type: string): string {
		switch (type) {
			case 'markdown': return 'mdi:text';
			case 'chart': return 'mdi:chart-bar';
			case 'image': return 'mdi:image';
			case 'table': return 'mdi:table';
			case 'html': return 'mdi:code-tags';
			case 'map': return 'mdi:map-marker';
			case 'interactive': return 'mdi:puzzle';
			default: return 'mdi:cube-outline';
		}
	}
</script>

<!-- Toolbar: floats above block in the inter-block gap so it doesn't overlap any in-block toolbars (e.g. MarkdownToolbar) -->
<div class="absolute -top-8 right-0 z-20 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity bg-card border border-border rounded-md shadow-sm px-1 py-0.5">
	<!-- Block type icon -->
	<span class="text-muted-foreground mr-1">
		<Icon icon={iconForType(block.type)} class="size-3.5" />
	</span>

	<!-- Move up -->
	<button
		class="btn btn-ghost btn-xs btn-square"
		onclick={onMoveUp}
		disabled={index === 0}
		title="Move block up"
		aria-label="Move block up"
	>
		<Icon icon="mdi:arrow-up" class="size-3.5" />
	</button>

	<!-- Move down -->
	<button
		class="btn btn-ghost btn-xs btn-square"
		onclick={onMoveDown}
		disabled={index === total - 1}
		title="Move block down"
		aria-label="Move block down"
	>
		<Icon icon="mdi:arrow-down" class="size-3.5" />
	</button>

	<!-- Delete -->
	<button
		class="btn btn-ghost btn-xs btn-square text-destructive hover:text-destructive"
		onclick={onDelete}
		title="Delete block"
		aria-label="Delete block"
	>
		<Icon icon="mdi:trash-can-outline" class="size-3.5" />
	</button>
</div>
