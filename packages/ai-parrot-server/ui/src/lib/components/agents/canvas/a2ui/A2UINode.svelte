<script lang="ts">
	// ai-parrot (FEAT-527): dispatch a single nested A2UI component descriptor
	// (or a Basic Catalog primitive shape) to the right display renderer.
	// Reuses the EXISTING infographic block renderers (Chart/DataTable/
	// Timeline) instead of a second rendering stack — only KPICard/InfoCard/
	// HtmlDocument/the Basic primitives are rendered inline here.
	import { getContext } from 'svelte';
	import { resolveProps } from './a2ui-binding';
	import { toChartBlockData } from './a2ui-chart-adapter';
	import { VIZ_CORE_CATALOG_ID, type SectionDescriptor } from './a2ui-types';
	import type { GraphProperties } from './A2UIGraph.svelte';
	import type { TableBlockData, TimelineBlockData } from '../infographic/infographic-types';
	import InfographicChartBlock from '../infographic/blocks/InfographicChartBlock.svelte';
	import InfographicTableBlock from '../infographic/blocks/InfographicTableBlock.svelte';
	import InfographicTimelineBlock from '../infographic/blocks/InfographicTimelineBlock.svelte';
	import InfographicHeroCardBlock from '../infographic/blocks/InfographicHeroCardBlock.svelte';
	import A2UIGraph from './A2UIGraph.svelte';
	import A2UINode from './A2UINode.svelte';
	import { LINKED_LANE_CONTEXT, FILTER_CONTEXT, type LinkedLane, type FilterController } from './linked';

	let {
		descriptor,
		dataModel,
		surfaceCatalogId
	}: {
		descriptor: SectionDescriptor;
		dataModel: Record<string, unknown>;
		/** The owning surface's default `catalogId` (FEAT-529 Module 0/7 v1.0
		 * resolution rule: a component's OWN `catalogId` wins, else this).
		 * Optional — omitted call sites simply never resolve to a non-default
		 * catalog, same as before this prop existed. */
		surfaceCatalogId?: string;
	} = $props();

	let component = $derived(descriptor.component);
	let properties = $derived(descriptor.properties ?? {});
	let resolved = $derived(resolveProps(properties, dataModel));

	// FEAT-598 (TASK-3795): FilterBar branch. `lane` is a stable proxy set once by `A2UISurface`
	// (undefined only in a component tree with no A2UISurface ancestor, e.g. a bare unit test) —
	// its own `setParam` no-ops when there is no active linked lane (baked surface). `filterCtl` is
	// the local-filter counterpart (works even on a surface with no data sources at all, §7.4).
	const lane = getContext<LinkedLane | undefined>(LINKED_LANE_CONTEXT);
	const filterCtl = getContext<FilterController | undefined>(FILTER_CONTEXT);

	interface FilterBarOption {
		label: string;
		value: string;
	}
	interface RawFilterBarFilter {
		column: string;
		label?: string;
		options?: { label?: string; value?: string }[];
		multiple?: boolean;
		param?: { source?: string; name?: string };
	}
	interface NormalizedFilter {
		column: string;
		label: string;
		options: FilterBarOption[];
		multiple: boolean;
		initialValue: string[];
		param?: { source: string; name: string };
	}

	// Unlowered FilterBar: `properties.filters[*] = {column, label, options, multiple?, param?}`
	// (TASK-3789 wire). A FilterBar with NO `filters` at all (or an empty list) is malformed input
	// (the catalog schema requires `filters`) — falls through to the generic "not supported"
	// placeholder below, same as before this task.
	let rawFilters = $derived(
		component === 'FilterBar' && Array.isArray((properties as { filters?: unknown }).filters)
			? ((properties as { filters: RawFilterBarFilter[] }).filters)
			: null,
	);
	// Lowered FilterBar: `Row{metadata.extensions.parrot_variant: "filter-bar"}` of `ChoicePicker`
	// children, each tagged `metadata.extensions.parrot_role: "filter"` +
	// `parrot_filter_column` (+ NEW `parrot_param`, TASK-3789) — `catalog/parrot/filterbar.py:lower()`.
	let isFilterBarRow = $derived(
		(properties.metadata as { extensions?: Record<string, unknown> } | undefined)?.extensions
			?.parrot_variant === 'filter-bar',
	);
	let isFilterBarBranch = $derived(
		(rawFilters !== null && rawFilters.length > 0) || (component === 'Row' && isFilterBarRow),
	);

	let normalizedFilters = $derived.by((): NormalizedFilter[] => {
		if (rawFilters && rawFilters.length > 0) {
			return rawFilters.map((f): NormalizedFilter => {
				const options = (f.options ?? []).map((o) => ({ label: o.label ?? o.value ?? '', value: o.value ?? '' }));
				return {
					column: f.column,
					label: f.label ?? f.column,
					options,
					multiple: Boolean(f.multiple),
					// Mirrors the backend's `_lower_filter`: exactly one option -> pre-selected; else "all".
					initialValue: options.length === 1 ? [options[0].value] : [],
					param: f.param?.source && f.param?.name ? { source: f.param.source, name: f.param.name } : undefined,
				};
			});
		}
		if (component === 'Row' && isFilterBarRow) {
			const children = Array.isArray(properties.children) ? (properties.children as SectionDescriptor[]) : [];
			return children
				.filter((child) => child.component === 'ChoicePicker')
				.map((child): NormalizedFilter => {
					const childProps = (child.properties ?? {}) as Record<string, unknown>;
					const extensions =
						(childProps.metadata as { extensions?: Record<string, unknown> } | undefined)?.extensions ?? {};
					const param = extensions.parrot_param as { source?: string; name?: string } | undefined;
					const options = Array.isArray(childProps.options) ? (childProps.options as FilterBarOption[]) : [];
					return {
						column: String(extensions.parrot_filter_column ?? ''),
						label: String(childProps.label ?? extensions.parrot_filter_column ?? ''),
						options,
						multiple: childProps.variant === 'multipleSelection',
						initialValue: Array.isArray(childProps.value) ? (childProps.value as string[]).map(String) : [],
						param: param?.source && param?.name ? { source: param.source, name: param.name } : undefined,
					};
				});
		}
		return [];
	});

	// Selected values per filter column — seeded once from each filter's initial `value`
	// (checkbox state only; seeding never itself triggers a fetch or a local filter — that only
	// happens on explicit user interaction, see `toggleOption`).
	let selected = $state<Record<string, string[]>>({});
	let filtersSeeded = false;
	$effect(() => {
		if (!filtersSeeded && normalizedFilters.length > 0) {
			filtersSeeded = true;
			const seed: Record<string, string[]> = {};
			for (const filter of normalizedFilters) seed[filter.column] = filter.initialValue;
			selected = seed;
		}
	});

	function toggleOption(filter: NormalizedFilter, value: string, checked: boolean): void {
		const current = selected[filter.column] ?? [];
		const next = filter.multiple
			? checked
				? [...current, value]
				: current.filter((v) => v !== value)
			: checked
				? [value]
				: [];
		selected = { ...selected, [filter.column]: next };
		if (filter.param) {
			// parrot_param: re-fetch that ONE source (spec §7.4) — never local filtering for this one.
			void lane?.setParam(filter.param.source, filter.param.name, filter.multiple ? next : (next[0] ?? null));
		} else {
			// No param: filter locally, over the already-embedded dataModel (spec §7.4 scoping rule).
			filterCtl?.setFilter(filter.column, next);
		}
	}

	// FEAT-529: a nested authored descriptor carries its OWN `catalogId`
	// (`{"component": "Graph", "catalogId": VIZ_CORE, "properties": {...}}`);
	// `A2UISurface.svelte`'s root-dispatch shape instead nests the whole
	// wire `Component` (which may carry its own `catalogId`) as `properties`
	// — check both so either call shape resolves correctly.
	let componentCatalogId = $derived(
		descriptor.catalogId ?? (properties as { catalogId?: string }).catalogId,
	);
	let resolvedCatalogId = $derived(componentCatalogId ?? surfaceCatalogId);
	let isVizCoreGraph = $derived(component === 'Graph' && resolvedCatalogId === VIZ_CORE_CATALOG_ID);

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
{:else if isVizCoreGraph}
	<!-- FEAT-529: dispatched ONLY when this Graph resolves (own catalogId,
	     else the surface default) to viz-core — a bare "Graph" on a
	     Parrot-default surface falls through to the unsupported placeholder
	     below, same as any other unknown component (spec: no $ref from
	     viz-core to Basic/Parrot). -->
	<A2UIGraph properties={resolved as unknown as GraphProperties} {dataModel} />
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
{:else if isFilterBarBranch}
	<div class="a2ui-filter-bar flex flex-wrap gap-4 items-start" data-testid="filter-bar">
		{#each normalizedFilters as filter (filter.column)}
			<fieldset class="flex flex-col gap-1 border-0 p-0 m-0">
				<legend class="text-xs font-semibold text-muted-foreground">{filter.label}</legend>
				{#each filter.options as option (option.value)}
					<label class="flex items-center gap-1 text-xs">
						<input
							type="checkbox"
							checked={(selected[filter.column] ?? []).includes(option.value)}
							onchange={(e) =>
								toggleOption(filter, option.value, (e.currentTarget as HTMLInputElement).checked)}
						/>
						{option.label}
					</label>
				{/each}
			</fieldset>
		{/each}
	</div>
{:else if component === 'List' || component === 'Row' || component === 'Column'}
	<div class={component === 'Row' ? 'flex flex-row gap-3' : 'flex flex-col gap-2'}>
		{#each childDescriptors as child, i (i)}
			<A2UINode descriptor={child} {dataModel} {surfaceCatalogId} />
		{/each}
	</div>
{:else if component === 'Tabs'}
	<div class="flex flex-col gap-2">
		{#each tabsData as tab, i (i)}
			<div>
				{#if tab.title}<h4 class="text-xs font-semibold text-muted-foreground mb-1">{tab.title}</h4>{/if}
				<A2UINode descriptor={tab.child} {dataModel} {surfaceCatalogId} />
			</div>
		{/each}
	</div>
{:else}
	<div class="a2ui-placeholder text-sm text-muted-foreground italic p-3 border border-dashed border-border rounded">
		{component ?? 'Unknown component'} is not supported in this view
	</div>
{/if}
