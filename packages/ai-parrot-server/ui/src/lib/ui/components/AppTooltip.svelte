<script lang="ts">
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';

	let {
		content,
		placement = 'top',
		children
	}: {
		content: string;
		placement?: 'top' | 'bottom' | 'left' | 'right';
		children: Snippet;
	} = $props();
</script>

<Tooltip.Provider delayDuration={200}>
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				<span {...props}>
					{@render children()}
				</span>
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Portal>
			<Tooltip.Content
				side={placement}
				sideOffset={4}
				class="z-50 rounded-md bg-gray-900 px-3 py-1.5 text-xs text-white shadow-lg dark:bg-gray-700"
			>
				{content}
				<Tooltip.Arrow class="fill-gray-900 dark:fill-gray-700" />
			</Tooltip.Content>
		</Tooltip.Portal>
	</Tooltip.Root>
</Tooltip.Provider>
