<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { HeroCardBlockData, TrendDirection } from '../infographic-types';

	let { label, value, icon, trend, trend_value, comparison_period, color }: HeroCardBlockData =
		$props();

	function trendIcon(t: TrendDirection): string {
		if (t === 'up') return 'mdi:trending-up';
		if (t === 'down') return 'mdi:trending-down';
		return 'mdi:trending-neutral';
	}

	function trendColor(t: TrendDirection): string {
		if (t === 'up') return 'text-emerald-500';
		if (t === 'down') return 'text-red-500';
		return 'text-muted-foreground';
	}
</script>

<div
	class="flex flex-col items-center justify-center rounded-xl border border-border bg-card p-5 text-center shadow-sm gap-1 {color ? 'border-t-[3px]' : ''}"
	style:border-top-color={color || 'transparent'}
>
	{#if icon}
		<div class="mb-1 text-2xl">
			<Icon {icon} class="size-7 text-muted-foreground" />
		</div>
	{/if}
	<div class="text-3xl font-bold text-foreground leading-none">{value}</div>
	<div class="text-xs text-muted-foreground font-medium mt-1">{label}</div>
	{#if trend}
		<div class="flex items-center gap-1 mt-1 text-xs {trendColor(trend)}">
			<Icon icon={trendIcon(trend)} class="size-3.5" />
			{#if trend_value !== undefined}
				<span>{trend_value}</span>
			{/if}
			{#if comparison_period}
				<span class="text-muted-foreground">vs {comparison_period}</span>
			{/if}
		</div>
	{/if}
</div>
