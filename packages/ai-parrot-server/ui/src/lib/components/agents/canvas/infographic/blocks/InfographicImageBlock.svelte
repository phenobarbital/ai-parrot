<script lang="ts">
	import type { ImageBlockData } from '../infographic-types';

	let { url, alt = '', caption, width, height }: ImageBlockData = $props();
</script>

<figure class="rounded-lg bg-card border border-border p-3">
	<img
		src={url}
		{alt}
		width={width ?? undefined}
		height={height ?? undefined}
		class="rounded max-w-full h-auto mx-auto"
		loading="lazy"
	/>
	{#if caption}
		<figcaption class="text-xs text-muted-foreground text-center mt-2">{caption}</figcaption>
	{/if}
</figure>
