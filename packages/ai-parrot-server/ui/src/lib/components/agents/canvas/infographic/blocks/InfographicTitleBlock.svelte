<script lang="ts">
	import type { TitleBlockData } from '../infographic-types';

	let { title, subtitle, author, date, logo_url }: TitleBlockData = $props();
</script>

<div class="w-full rounded-lg overflow-hidden bg-gradient-to-br from-primary/80 to-primary text-primary-foreground p-8 text-center">
	{#if logo_url}
		<img src={logo_url} alt="Logo" class="h-10 mx-auto mb-4 object-contain" />
	{/if}
	<h1 class="text-3xl font-bold leading-tight mb-2">{title}</h1>
	{#if subtitle}
		<p class="text-base opacity-85 mb-3">{subtitle}</p>
	{/if}
	{#if author || date}
		<div class="flex items-center justify-center gap-3 text-sm opacity-70 mt-2">
			{#if author}
				<span>{author}</span>
			{/if}
			{#if author && date}
				<span>·</span>
			{/if}
			{#if date}
				<span>{date}</span>
			{/if}
		</div>
	{/if}
</div>
