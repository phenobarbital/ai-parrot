<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import type { Snippet } from 'svelte';

	let {
		placement = 'bottom-start',
		trigger,
		children
	}: {
		placement?: 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end';
		trigger: Snippet;
		children: Snippet;
	} = $props();

	const sideMap: Record<string, 'top' | 'bottom'> = {
		'bottom-start': 'bottom',
		'bottom-end': 'bottom',
		'top-start': 'top',
		'top-end': 'top'
	};

	const alignMap: Record<string, 'start' | 'end'> = {
		'bottom-start': 'start',
		'bottom-end': 'end',
		'top-start': 'start',
		'top-end': 'end'
	};
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<span {...props}>
				{@render trigger()}
			</span>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Portal>
		<DropdownMenu.Content
			side={sideMap[placement]}
			align={alignMap[placement]}
			sideOffset={4}
			class="z-50 min-w-[8rem] rounded-lg border border-base-200 bg-base-100 p-1 shadow-lg"
		>
			{@render children()}
		</DropdownMenu.Content>
	</DropdownMenu.Portal>
</DropdownMenu.Root>
