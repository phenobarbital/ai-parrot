<script lang="ts">
	import type { BulletListBlockData } from '../infographic-types';

	let { title, items, ordered = false }: BulletListBlockData = $props();
</script>

<div class="rounded-lg bg-card border border-border p-5">
	{#if title}
		<h3 class="text-base font-semibold text-foreground mb-3">{title}</h3>
	{/if}
	{#if ordered}
		<ol class="list-decimal list-inside space-y-1.5 text-sm text-foreground">
			{#each items as item}
				<li>{item}</li>
			{/each}
		</ol>
	{:else}
		<ul class="list-disc list-inside space-y-1.5 text-sm text-foreground">
			{#each items as item}
				<li>{item}</li>
			{/each}
		</ul>
	{/if}
</div>
