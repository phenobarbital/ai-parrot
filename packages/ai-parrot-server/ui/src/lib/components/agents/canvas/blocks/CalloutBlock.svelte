<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { CalloutBlockData, CalloutLevel } from '../canvas-block-types';

	let {
		data,
		onUpdate,
		previewMode = false
	}: {
		data: CalloutBlockData;
		onUpdate: (data: CalloutBlockData) => void;
		previewMode?: boolean;
	} = $props();

	let isEditing = $state(true);

	$effect(() => {
		if (previewMode) isEditing = false;
		else if (!data.content?.trim()) isEditing = true;
	});

	const levelConfig: Record<CalloutLevel, { icon: string; bg: string; border: string; text: string }> = {
		info:    { icon: 'mdi:information-outline', bg: 'bg-blue-50 dark:bg-blue-950/30', border: 'border-blue-400', text: 'text-blue-700 dark:text-blue-300' },
		success: { icon: 'mdi:check-circle-outline', bg: 'bg-emerald-50 dark:bg-emerald-950/30', border: 'border-emerald-400', text: 'text-emerald-700 dark:text-emerald-300' },
		warning: { icon: 'mdi:alert-outline', bg: 'bg-amber-50 dark:bg-amber-950/30', border: 'border-amber-400', text: 'text-amber-700 dark:text-amber-300' },
		error:   { icon: 'mdi:alert-circle-outline', bg: 'bg-red-50 dark:bg-red-950/30', border: 'border-red-400', text: 'text-red-700 dark:text-red-300' },
		tip:     { icon: 'mdi:lightbulb-outline', bg: 'bg-violet-50 dark:bg-violet-950/30', border: 'border-violet-400', text: 'text-violet-700 dark:text-violet-300' },
	};

	let config = $derived(levelConfig[data.level] ?? levelConfig.info);

	const levelOptions: { value: CalloutLevel; label: string }[] = [
		{ value: 'info', label: 'Info' },
		{ value: 'success', label: 'Success' },
		{ value: 'warning', label: 'Warning' },
		{ value: 'error', label: 'Error' },
		{ value: 'tip', label: 'Tip' },
	];
</script>

{#if isEditing && !previewMode}
	<div class="p-4 flex flex-col gap-2">
		<div class="grid grid-cols-2 gap-2">
			<select class="select select-sm text-xs" value={data.level} onchange={(e) => onUpdate({ ...data, level: e.currentTarget.value as CalloutLevel })}>
				{#each levelOptions as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
			<input class="input input-sm text-xs" placeholder="Title (optional)" value={data.title ?? ''} oninput={(e) => onUpdate({ ...data, title: e.currentTarget.value || undefined })} />
		</div>
		<textarea
			class="textarea textarea-sm text-xs min-h-[60px]"
			placeholder="Callout content..."
			value={data.content}
			oninput={(e) => onUpdate({ ...data, content: e.currentTarget.value })}
		></textarea>
		<button class="self-start text-xs text-muted-foreground hover:text-foreground" onclick={() => (isEditing = false)}>Preview</button>
	</div>
{:else}
	<button
		class="w-full text-left"
		onclick={() => { if (!previewMode) isEditing = true; }}
		disabled={previewMode}
	>
		<div class="flex items-start gap-3 rounded-lg border-l-4 {config.border} {config.bg} p-4">
			<Icon icon={config.icon} class="size-5 {config.text} shrink-0 mt-0.5" />
			<div class="min-w-0">
				{#if data.title}
					<p class="text-sm font-semibold {config.text} mb-1">{data.title}</p>
				{/if}
				{#if data.content?.trim()}
					<p class="text-sm text-foreground/80 leading-relaxed">{data.content}</p>
				{:else}
					<p class="text-sm text-muted-foreground/40 italic">Write callout content...</p>
				{/if}
			</div>
		</div>
	</button>
{/if}
