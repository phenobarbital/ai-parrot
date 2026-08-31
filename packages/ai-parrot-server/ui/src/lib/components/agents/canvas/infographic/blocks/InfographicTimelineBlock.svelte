<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { TimelineBlockData } from '../infographic-types';

	let { title, items }: TimelineBlockData = $props();
</script>

<div class="rounded-lg bg-card border border-border p-5">
	{#if title}
		<h3 class="text-base font-semibold text-foreground mb-4">{title}</h3>
	{/if}
	<div class="relative pl-6">
		<!-- Vertical line -->
		<div class="absolute left-2 top-1 bottom-1 w-px bg-border"></div>
		{#each items as item, i}
			<div class="relative pb-5 last:pb-0">
				<!-- Dot -->
				<div
					class="absolute -left-4 top-1 size-3 rounded-full border-2 border-background"
					style="background-color: {item.color ?? 'hsl(var(--primary))'}"
				></div>
				<div>
					{#if item.date}
						<span class="text-xs text-muted-foreground">{item.date}</span>
					{/if}
					<h4 class="text-sm font-medium text-foreground">{item.title}</h4>
					{#if item.description}
						<p class="text-xs text-muted-foreground mt-0.5">{item.description}</p>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>
