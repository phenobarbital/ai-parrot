<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import type { Snippet } from 'svelte';

	let {
		onclick,
		disabled = false,
		children
	}: {
		onclick?: () => void;
		disabled?: boolean;
		children: Snippet;
	} = $props();
</script>

<DropdownMenu.Item
	{disabled}
	onSelect={onclick ? () => onclick() : undefined}
	class="flex w-full cursor-pointer items-center rounded-md px-3 py-2 text-sm text-base-content outline-none transition-colors hover:bg-base-200 focus:bg-base-200 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50"
>
	{@render children()}
</DropdownMenu.Item>
