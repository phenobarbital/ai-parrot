<script lang="ts">
	import type { DividerBlockData } from '../infographic-types';

	let { style = 'solid', label }: DividerBlockData = $props();

	const borderStyle: Record<string, string> = {
		solid: 'border-solid',
		dashed: 'border-dashed',
		dotted: 'border-dotted'
	};

	let cls = $derived(borderStyle[style ?? 'solid'] ?? 'border-solid');
</script>

{#if label}
	<div class="flex items-center gap-3 py-2">
		<hr class="flex-1 border-t {cls} border-border" />
		<span class="text-xs text-muted-foreground font-medium shrink-0">{label}</span>
		<hr class="flex-1 border-t {cls} border-border" />
	</div>
{:else}
	<hr class="border-t {cls} border-border my-2" />
{/if}
