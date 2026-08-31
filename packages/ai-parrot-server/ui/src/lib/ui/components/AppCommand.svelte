<script lang="ts">
	import * as Command from '$lib/ui/internal/shadcn/ui/command/index.js';

	type CommandItem = {
		value: string;
		label: string;
		group?: string;
	};

	let {
		placeholder = 'Search...',
		items = [],
		emptyMessage = 'No results found.',
		onselect,
	}: {
		placeholder?: string;
		items?: CommandItem[];
		emptyMessage?: string;
		onselect?: (value: string) => void;
	} = $props();

	let searchValue = $state('');

	// Group items by their group property
	let groupedItems = $derived.by(() => {
		const groups = new Map<string, CommandItem[]>();
		for (const item of items) {
			const group = item.group ?? '';
			if (!groups.has(group)) {
				groups.set(group, []);
			}
			groups.get(group)!.push(item);
		}
		return groups;
	});

	function handleSelect(value: string) {
		onselect?.(value);
	}
</script>

<Command.Root>
	<Command.Input {placeholder} bind:value={searchValue} />
	<Command.List>
		<Command.Empty>{emptyMessage}</Command.Empty>
		{#each [...groupedItems.entries()] as [group, groupItems]}
			{#if group}
				<Command.Group heading={group}>
					{#each groupItems as item (item.value)}
						<Command.Item value={item.value} onSelect={() => handleSelect(item.value)}>
							{item.label}
						</Command.Item>
					{/each}
				</Command.Group>
			{:else}
				{#each groupItems as item (item.value)}
					<Command.Item value={item.value} onSelect={() => handleSelect(item.value)}>
						{item.label}
					</Command.Item>
				{/each}
			{/if}
		{/each}
	</Command.List>
</Command.Root>
