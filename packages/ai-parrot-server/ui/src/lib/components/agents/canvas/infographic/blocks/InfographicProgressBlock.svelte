<script lang="ts">
	import type { ProgressBlockData } from '../infographic-types';

	let { title, items }: ProgressBlockData = $props();
</script>

<div class="rounded-lg bg-card border border-border p-5">
	{#if title}
		<h3 class="text-base font-semibold text-foreground mb-3">{title}</h3>
	{/if}
	<div class="space-y-3">
		{#each items as item}
			{@const max = item.max ?? 100}
			{@const pct = Math.min(100, Math.round((item.value / max) * 100))}
			<div>
				<div class="flex justify-between text-xs mb-1">
					<span class="text-foreground font-medium">{item.label}</span>
					<span class="text-muted-foreground">{pct}%</span>
				</div>
				<div class="h-2 rounded-full bg-muted overflow-hidden">
					<div
						class="h-full rounded-full transition-all"
						style="width: {pct}%; background-color: {item.color ?? 'hsl(var(--primary))'}"
					></div>
				</div>
			</div>
		{/each}
	</div>
</div>
