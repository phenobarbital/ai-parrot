<script lang="ts">
	// ai-parrot (FEAT-527): dispatch a single nested A2UI component descriptor
	// (or a Basic Catalog primitive shape) to the right display renderer.
	// Reuses the EXISTING infographic block renderers (Chart/DataTable/
	// Timeline) instead of a second rendering stack — only KPICard/InfoCard/
	// HtmlDocument/the Basic primitives are rendered inline here.
	import { resolveProps } from './a2ui-binding';
	import { toChartBlockData } from './a2ui-chart-adapter';
	import type { SectionDescriptor } from './a2ui-types';
	import type { TableBlockData, TimelineBlockData } from '../infographic/infographic-types';
	import InfographicChartBlock from '../infographic/blocks/InfographicChartBlock.svelte';
	import InfographicTableBlock from '../infographic/blocks/InfographicTableBlock.svelte';
	import InfographicTimelineBlock from '../infographic/blocks/InfographicTimelineBlock.svelte';
	import InfographicHeroCardBlock from '../infographic/blocks/InfographicHeroCardBlock.svelte';
	import A2UINode from './A2UINode.svelte';

	let {
		descriptor,
		dataModel
	}: { descriptor: SectionDescriptor; dataModel: Record<string, unknown> } = $props();

	let component = $derived(descriptor.component);
	let properties = $derived(descriptor.properties ?? {});
	let resolved = $derived(resolveProps(properties, dataModel));

	// -- DataTable: columns are {name, title?, ...}; resolved rows are
	// objects keyed by column name — reshape into TableBlockData's
	// positional rows.
	let tableData = $derived.by((): TableBlockData => {
		const cols = Array.isArray(properties.columns)
			? (properties.columns as { name: string; title?: string }[])
			: [];
		const rows = Array.isArray(resolved.data) ? (resolved.data as Record<string, unknown>[]) : [];
		return {
			title: typeof properties.title === 'string' ? properties.title : undefined,
			columns: cols.map((c) => c.title || c.name),
			rows: rows.map((row) => cols.map((c) => row?.[c.name] ?? null)),
		};
	});

	// -- Timeline: events[{timestamp, title, description}] -> items[{date, title, description}].
	let timelineData = $derived.by((): TimelineBlockData => {
		const events = Array.isArray(properties.events)
			? (properties.events as { timestamp?: string; title: string; description?: string }[])
			: [];
		return {
			title: typeof properties.title === 'string' ? properties.title : undefined,
			items: events.map((e) => ({ date: e.timestamp, title: e.title, description: e.description })),
		};
	});

	let childDescriptors = $derived(
		Array.isArray(properties.children) ? (properties.children as SectionDescriptor[]) : [],
	);
	let tabsData = $derived(
		Array.isArray(properties.tabs)
			? (properties.tabs as { title?: string; child: SectionDescriptor }[])
			: [],
	);
</script>

{#if component === 'KPICard'}
	<InfographicHeroCardBlock
		label={String(resolved.label ?? '')}
		value={(resolved.value as string | number) ?? ''}
		icon={resolved.icon as string | undefined}
		trend={resolved.trend as 'up' | 'down' | 'flat' | undefined}
		trend_value={resolved.delta as string | number | undefined}
		comparison_period={resolved.comparisonPeriod as string | undefined}
		color={resolved.color as string | undefined}
	/>
{:else if component === 'Chart'}
	<!-- Code-review fix: InfographicChartBlock already gates its own chart
	     internals behind features.charts (with an identical placeholder) and
	     renders title/description regardless of the flag — the outer gate
	     here duplicated the check AND, worse, suppressed title/description
	     whenever the flag was off. Let the delegated component own it. -->
	<InfographicChartBlock {...toChartBlockData(properties, dataModel)} />
{:else if component === 'DataTable'}
	<InfographicTableBlock {...tableData} />
{:else if component === 'Timeline'}
	<InfographicTimelineBlock {...timelineData} />
{:else if component === 'InfoCard'}
	<div class="rounded-lg border border-border bg-card p-4">
		{#if resolved.title}<h3 class="text-sm font-semibold text-foreground mb-1">{resolved.title}</h3>{/if}
		{#if resolved.subtitle}<p class="text-xs text-muted-foreground mb-2">{resolved.subtitle}</p>{/if}
		{#if resolved.badge}<span class="inline-block rounded bg-muted px-2 py-0.5 text-xs mb-2">{resolved.badge}</span>{/if}
		{#if resolved.body}<p class="text-sm text-foreground">{resolved.body}</p>{/if}
		{#if resolved.footer}<p class="text-xs text-muted-foreground mt-2">{resolved.footer}</p>{/if}
	</div>
{:else if component === 'HtmlDocument'}
	<section class="a2ui-html-document">
		{#if resolved.title}<h3 class="text-sm font-semibold mb-1">{resolved.title}</h3>{/if}
		{#if resolved.html !== undefined}
			<iframe
				title={String(resolved.title ?? 'Document')}
				sandbox="allow-scripts"
				referrerpolicy="no-referrer"
				srcdoc={String(resolved.html)}
				style="width:100%;min-height:480px;border:1px solid var(--border, #ccc)"
			></iframe>
		{:else}
			<iframe
				title={String(resolved.title ?? 'Document')}
				sandbox="allow-scripts"
				referrerpolicy="no-referrer"
				src={String(resolved.srcUrl ?? '')}
				style="width:100%;min-height:480px;border:1px solid var(--border, #ccc)"
			></iframe>
		{/if}
	</section>
{:else if component === 'Text'}
	<p class="a2ui-text text-sm text-foreground">{resolved.text ?? ''}</p>
{:else if component === 'Image'}
	<img
		src={String(resolved.url ?? '')}
		alt={String(resolved.description ?? '')}
		class="max-w-full rounded"
	/>
{:else if component === 'Divider'}
	<hr class="border-t border-border my-2" />
{:else if component === 'CheckBox'}
	<label class="flex items-center gap-2 text-sm">
		<input type="checkbox" checked={Boolean(resolved.value)} disabled />
		<span>{resolved.label ?? ''}</span>
	</label>
{:else if component === 'List' || component === 'Row' || component === 'Column'}
	<div class={component === 'Row' ? 'flex flex-row gap-3' : 'flex flex-col gap-2'}>
		{#each childDescriptors as child, i (i)}
			<A2UINode descriptor={child} {dataModel} />
		{/each}
	</div>
{:else if component === 'Tabs'}
	<div class="flex flex-col gap-2">
		{#each tabsData as tab, i (i)}
			<div>
				{#if tab.title}<h4 class="text-xs font-semibold text-muted-foreground mb-1">{tab.title}</h4>{/if}
				<A2UINode descriptor={tab.child} {dataModel} />
			</div>
		{/each}
	</div>
{:else}
	<div class="a2ui-placeholder text-sm text-muted-foreground italic p-3 border border-dashed border-border rounded">
		{component ?? 'Unknown component'} is not supported in this view
	</div>
{/if}
