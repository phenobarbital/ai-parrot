<script lang="ts">
	import type { SummaryBlockData } from '../infographic-types';

	let { title, content, highlight }: SummaryBlockData = $props();

	/**
	 * Minimal markdown-like rendering: bold (**text**), italic (*text*), line breaks.
	 * Sanitized — no user-controllable HTML injection beyond the text content.
	 */
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

<div
	class="rounded-lg p-5 {highlight
		? 'bg-primary/10 border-l-4 border-primary'
		: 'bg-card border border-border'}"
>
	{#if title}
		<h3 class="text-base font-semibold text-foreground mb-2">{title}</h3>
	{/if}
	<div class="text-sm text-foreground leading-relaxed">
		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		{@html renderContent(content)}
	</div>
</div>
