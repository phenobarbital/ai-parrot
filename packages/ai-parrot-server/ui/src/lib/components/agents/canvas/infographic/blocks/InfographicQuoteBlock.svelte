<script lang="ts">
	import type { QuoteBlockData } from '../infographic-types';

	let { text, author, source }: QuoteBlockData = $props();
</script>

<blockquote class="rounded-lg bg-card border border-border border-l-4 border-l-primary/60 p-5">
	<p class="text-sm italic text-foreground leading-relaxed">"{text}"</p>
	{#if author || source}
		<footer class="mt-2 text-xs text-muted-foreground">
			{#if author}
				<span class="font-medium">&mdash; {author}</span>
			{/if}
			{#if source}
				<span class="ml-1">({source})</span>
			{/if}
		</footer>
	{/if}
</blockquote>
