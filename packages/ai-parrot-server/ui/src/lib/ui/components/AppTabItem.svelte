<script lang="ts">
	/**
	 * @deprecated Use AppTabs with the `tabs` prop and snippet children instead.
	 * This component is kept for backward compatibility but AppTabs handles
	 * both triggers and content panels internally.
	 *
	 * Usage of AppTabs:
	 * ```svelte
	 * <AppTabs tabs={[{value: 'a', title: 'Tab A'}, {value: 'b', title: 'Tab B'}]}>
	 *   {#snippet children(tab)}
	 *     {#if tab === 'a'}Content A{/if}
	 *     {#if tab === 'b'}Content B{/if}
	 *   {/snippet}
	 * </AppTabs>
	 * ```
	 */
	import { Tabs } from 'bits-ui';
	import type { Snippet } from 'svelte';

	let {
		value,
		title: _title,
		children
	}: {
		value: string;
		title: string;
		children: Snippet;
	} = $props();
</script>

<Tabs.Content {value} class="mt-4">
	{@render children()}
</Tabs.Content>
