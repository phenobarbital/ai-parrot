<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { CalloutBlockData } from '../infographic-types';

	let { level, title, content }: CalloutBlockData = $props();

	const config: Record<string, { icon: string; border: string; bg: string }> = {
		info: { icon: 'mdi:information-outline', border: 'border-l-blue-500', bg: 'bg-blue-500/10' },
		success: { icon: 'mdi:check-circle-outline', border: 'border-l-green-500', bg: 'bg-green-500/10' },
		warning: { icon: 'mdi:alert-outline', border: 'border-l-amber-500', bg: 'bg-amber-500/10' },
		error: { icon: 'mdi:alert-circle-outline', border: 'border-l-red-500', bg: 'bg-red-500/10' },
		tip: { icon: 'mdi:lightbulb-outline', border: 'border-l-purple-500', bg: 'bg-purple-500/10' }
	};

	let style = $derived(config[level] ?? config.info);
</script>

<div class="rounded-lg border border-border border-l-4 {style.border} {style.bg} p-5">
	<div class="flex items-start gap-2">
		<Icon icon={style.icon} class="size-4 mt-0.5 shrink-0 text-foreground" />
		<div class="min-w-0">
			{#if title}
				<h3 class="text-sm font-semibold text-foreground mb-1">{title}</h3>
			{/if}
			<p class="text-sm text-foreground leading-relaxed">{content}</p>
		</div>
	</div>
</div>
