<script lang="ts">
	import { Tabs } from 'bits-ui';
	import type { Snippet } from 'svelte';

	type Tab = {
		value: string;
		title: string;
	};

	let {
		value = $bindable(''),
		tabs,
		children,
		actions,
		fillHeight = false
	}: {
		value?: string;
		tabs: Tab[];
		children: Snippet<[string]>;
		actions?: Snippet;
		fillHeight?: boolean;
	} = $props();

	// Default to first tab if no value set
	$effect(() => {
		if (!value && tabs.length > 0) {
			value = tabs[0].value;
		}
	});
</script>

<Tabs.Root
	bind:value
	class={fillHeight ? 'flex h-full w-full flex-col overflow-hidden' : 'w-full'}
>
	<Tabs.List
		class={fillHeight
			? 'flex shrink-0 items-center border-b border-base-200'
			: 'flex items-center border-b border-base-200'}
	>
		{#each tabs as tab (tab.value)}
			<Tabs.Trigger
				value={tab.value}
				class="inline-flex items-center border-b-2 border-transparent px-4 py-2 text-sm font-medium text-gray-500 transition-colors hover:border-gray-300 hover:text-gray-700 data-[state=active]:border-primary-600 data-[state=active]:text-primary-600 dark:text-gray-400 dark:hover:text-gray-300 dark:data-[state=active]:border-primary-400 dark:data-[state=active]:text-primary-400"
			>
				{tab.title}
			</Tabs.Trigger>
		{/each}
		{#if actions}
			<div class="ml-auto flex items-center pr-1">
				{@render actions()}
			</div>
		{/if}
	</Tabs.List>

	{#each tabs as tab (tab.value)}
		<Tabs.Content
			value={tab.value}
			class={fillHeight
				? 'mt-2 min-h-0 flex-1 overflow-hidden data-[state=inactive]:hidden'
				: 'mt-4'}
		>
			{@render children(tab.value)}
		</Tabs.Content>
	{/each}
</Tabs.Root>
