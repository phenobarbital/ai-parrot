<script lang="ts">
	// ai-parrot (FEAT-527): render an A2UI `Infographic`/`Report` root
	// component — title/subtitle, then sections (stacked when there is
	// exactly one, tabbed via AppTabs when there is more than one, mirroring
	// the backend's own Tabs-vs-Column lowering rule, TASK-2860).
	import AppTabs from '$lib/ui/components/AppTabs.svelte';
	import A2UINode from './A2UINode.svelte';
	import type { InfographicSection, SectionDescriptor, WireComponent } from './a2ui-types';

	let {
		component,
		dataModel
	}: { component: WireComponent; dataModel: Record<string, unknown> } = $props();

	let title = $derived(typeof component.title === 'string' ? component.title : '');
	let subtitle = $derived(typeof component.subtitle === 'string' ? component.subtitle : undefined);
	let sections = $derived(
		Array.isArray(component.sections) ? (component.sections as InfographicSection[]) : [],
	);
	let tabs = $derived(
		sections.map((s, i) => ({ value: String(i), title: s.heading || `Section ${i + 1}` })),
	);

	/**
	 * FEAT-527 (mirrors TASK-2860's backend `_lower_section` half-width `Row`
	 * grouping): group consecutive `properties.layout === "half"` component
	 * descriptors into pairs of a 2-column grid row; anything else (a "full"/
	 * omitted layout, or an odd trailing half) renders as its own full-width
	 * row.
	 */
	function groupByLayout(components: SectionDescriptor[]): SectionDescriptor[][] {
		const groups: SectionDescriptor[][] = [];
		let i = 0;
		while (i < components.length) {
			const descriptor = components[i];
			const isHalf = descriptor.properties?.layout === 'half';
			if (isHalf) {
				const pair = [descriptor];
				const next = components[i + 1];
				if (next?.properties?.layout === 'half') {
					pair.push(next);
					i += 1;
				}
				groups.push(pair);
			} else {
				groups.push([descriptor]);
			}
			i += 1;
		}
		return groups;
	}
</script>

<div class="a2ui-infographic flex flex-col gap-3">
	{#if title}<h2 class="text-lg font-semibold text-foreground">{title}</h2>{/if}
	{#if subtitle}<p class="text-sm text-muted-foreground">{subtitle}</p>{/if}

	{#snippet section(s: InfographicSection)}
		<div class="flex flex-col gap-3">
			{#if s.text}<p class="text-sm text-foreground">{s.text}</p>{/if}
			{#each groupByLayout(s.components ?? []) as group, gi (gi)}
				{#if group.length > 1}
					<div class="grid grid-cols-2 gap-3">
						{#each group as descriptor, di (di)}
							<A2UINode {descriptor} {dataModel} />
						{/each}
					</div>
				{:else}
					<A2UINode descriptor={group[0]} {dataModel} />
				{/if}
			{/each}
		</div>
	{/snippet}

	{#if sections.length > 1}
		<AppTabs {tabs}>
			{#snippet children(value: string)}
				{@render section(sections[Number(value)])}
			{/snippet}
		</AppTabs>
	{:else if sections.length === 1}
		{@render section(sections[0])}
	{/if}
</div>
