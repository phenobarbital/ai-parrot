<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { HeroCardBlockData } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: HeroCardBlockData;
		onUpdate: (data: HeroCardBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(false);

	$effect(() => {
		if (previewMode) isEditing = false;
	});

	function update(partial: Partial<HeroCardBlockData>) {
		onUpdate({ ...data, ...partial });
	}

	const trendOptions: { value: string; label: string }[] = [
		{ value: '', label: 'None' },
		{ value: 'up', label: 'Up' },
		{ value: 'down', label: 'Down' },
		{ value: 'flat', label: 'Flat' },
	];

	function trendIcon(t?: string): string {
		if (t === 'up') return 'mdi:trending-up';
		if (t === 'down') return 'mdi:trending-down';
		return 'mdi:trending-neutral';
	}

	function trendColor(t?: string): string {
		if (t === 'up') return 'text-emerald-500';
		if (t === 'down') return 'text-red-500';
		return 'text-muted-foreground';
	}
</script>

{#if isEditing && !previewMode}
	<div class="p-4 flex flex-col gap-2">
		<div class="grid grid-cols-2 gap-2">
			<input class="input input-sm text-xs" placeholder="Label (e.g. Revenue)" value={data.label} oninput={(e) => update({ label: e.currentTarget.value })} />
			<input class="input input-sm text-xs" placeholder="Value (e.g. $42K)" value={data.value} oninput={(e) => update({ value: e.currentTarget.value })} />
		</div>
		<div class="grid grid-cols-3 gap-2">
			<input class="input input-sm text-xs" placeholder="Icon (mdi:...)" value={data.icon ?? ''} oninput={(e) => update({ icon: e.currentTarget.value || undefined })} />
			<select class="select select-sm text-xs" value={data.trend ?? ''} onchange={(e) => update({ trend: (e.currentTarget.value || undefined) as HeroCardBlockData['trend'] })}>
				{#each trendOptions as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
			<input class="input input-sm text-xs" placeholder="Trend value" value={data.trend_value ?? ''} oninput={(e) => update({ trend_value: e.currentTarget.value || undefined })} />
		</div>
		<input class="input input-sm text-xs" placeholder="Accent color (e.g. #3b82f6)" value={data.color ?? ''} oninput={(e) => update({ color: e.currentTarget.value || undefined })} />
		<button class="self-start text-xs text-muted-foreground hover:text-foreground" onclick={() => (isEditing = false)}>Preview</button>
	</div>
{:else}
	<button
		class="w-full text-left"
		onclick={() => { if (!previewMode) isEditing = true; }}
		disabled={previewMode}
	>
		<div
			class="flex flex-col items-center justify-center rounded-xl border border-border bg-card p-5 text-center shadow-sm gap-1 {data.color ? 'border-t-[3px]' : ''}"
			style:border-top-color={data.color || 'transparent'}
		>
			{#if data.icon}
				<div class="mb-1 text-2xl">
					<Icon icon={data.icon} class="size-7 text-muted-foreground" />
				</div>
			{/if}
			<div class="text-3xl font-bold text-foreground leading-none">{data.value || 'Value'}</div>
			<div class="text-xs text-muted-foreground font-medium mt-1">{data.label || 'Label'}</div>
			{#if data.trend}
				<div class="flex items-center gap-1 mt-1 text-xs {trendColor(data.trend)}">
					<Icon icon={trendIcon(data.trend)} class="size-3.5" />
					{#if data.trend_value}
						<span>{data.trend_value}</span>
					{/if}
				</div>
			{/if}
		</div>
	</button>
{/if}
