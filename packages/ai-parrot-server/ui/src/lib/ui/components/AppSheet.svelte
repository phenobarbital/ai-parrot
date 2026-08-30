<script lang="ts">
	import * as Sheet from '$lib/ui/internal/shadcn/ui/sheet/index.js';
	import type { Snippet } from 'svelte';

	let {
		open = $bindable(false),
		side = 'right',
		size = 'md',
		title,
		description,
		children,
		footer,
		onclose,
	}: {
		open: boolean;
		side?: 'left' | 'right' | 'top' | 'bottom';
		size?: 'sm' | 'md' | 'lg';
		title?: string;
		description?: string;
		children: Snippet;
		footer?: Snippet;
		onclose?: () => void;
	} = $props();

	const sizeClasses: Record<string, string> = {
		sm: 'sm:max-w-sm',
		md: 'sm:max-w-md',
		lg: 'sm:max-w-lg',
	};

	function handleOpenChange(value: boolean) {
		open = value;
		if (!value && onclose) {
			onclose();
		}
	}
</script>

<Sheet.Root bind:open onOpenChange={handleOpenChange}>
	<Sheet.Content {side} class={sizeClasses[size]}>
		{#if title || description}
			<Sheet.Header>
				{#if title}
					<Sheet.Title>{title}</Sheet.Title>
				{/if}
				{#if description}
					<Sheet.Description>{description}</Sheet.Description>
				{/if}
			</Sheet.Header>
		{/if}

		{@render children()}

		{#if footer}
			<Sheet.Footer>
				{@render footer()}
			</Sheet.Footer>
		{/if}
	</Sheet.Content>
</Sheet.Root>
