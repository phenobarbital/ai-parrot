<script lang="ts">
	// ai-parrot (FEAT-527): root dispatcher for an A2UI v1.0 envelope —
	// `Infographic`/`Report` roots render via `A2UIInfographic` (title +
	// sections-as-tabs); anything else (a bare Chart/DataTable/KPICard/…
	// widget) renders via `A2UINode` directly. Gated behind `features.a2ui`
	// by the caller (`InfographicCanvas.svelte`, TASK-2868) — this component
	// itself has no gate of its own so it stays independently testable.
	//
	// FEAT-598 (TASK-3795): stateful over `dataModel` — a surface whose
	// `metadata.extensions.parrot_data_sources` is present (`getDataSources`)
	// mounts a `createLinkedLane` that fetches/refreshes each source and
	// patches `dataModel[key] = {rows: [...]}` in place (AC10/AC16); a baked
	// surface (`sources === null`) never creates a lane and never fetches —
	// `dataModel` then stays exactly the envelope's own snapshot, byte-for-
	// byte the same render path as before this task (AC11).
	import { setContext } from 'svelte';
	import A2UIInfographic from './A2UIInfographic.svelte';
	import A2UINode from './A2UINode.svelte';
	import type { A2UIEnvelope, WireComponent } from './a2ui-types';
	import { getDataSources, type Row } from './linked/types';
	import {
		createLinkedLane,
		LINKED_LANE_CONTEXT,
		FILTER_CONTEXT,
		type LinkedLane,
		type SourceUpdate,
		type FilterController,
	} from './linked';
	import { querySourceBaseUrl, querySourceHeaders } from '$lib/api/querysource';
	import { getAuthHeaders } from '$lib/api/auth-headers';
	import { config } from '$lib/config';

	let {
		envelope,
		persistedSurfaceId,
		transformsBase,
	}: { envelope: A2UIEnvelope; persistedSurfaceId?: string; transformsBase?: string } = $props();

	let root = $derived<WireComponent | undefined>(
		envelope.createSurface.components.find((c) => c.id === 'root') ??
			envelope.createSurface.components[0],
	);
	let isInfographicLike = $derived(
		root !== undefined && (root.component === 'Infographic' || root.component === 'Report'),
	);

	// The canonical, latest-known rows per data-model root key — seeded from the envelope's own
	// snapshot, patched in place by the linked lane's `onUpdate` (never by local filtering, which
	// only ever narrows a DERIVED view — see `dataModel` below).
	let baseDataModel = $state<Record<string, unknown>>(structuredClone(envelope.createSurface.dataModel ?? {}));
	// FilterBar local-filter selections, keyed by data-model column; `[]` (or absent) = "all".
	let activeFilters = $state<Record<string, string[]>>({});
	let seededSurfaceId = envelope.createSurface.surfaceId;

	// Re-seed on a NEW envelope (a different surfaceId) — a baked surface never carries
	// `parrot_data_sources` so this is just a plain refresh of the static snapshot (AC11); filters
	// reset too, since they applied to the PREVIOUS surface's rows.
	$effect(() => {
		if (envelope.createSurface.surfaceId !== seededSurfaceId) {
			seededSurfaceId = envelope.createSurface.surfaceId;
			baseDataModel = structuredClone(envelope.createSurface.dataModel ?? {});
			activeFilters = {};
		}
	});

	/** Scoping rule (§7.4): a filter applies ONLY to a root key whose rows actually contain that
	 * column — derived from the data, never a hardcoded map; an unaffected key is left untouched. */
	let dataModel = $derived.by((): Record<string, unknown> => {
		const active = Object.entries(activeFilters).filter(([, values]) => values.length > 0);
		if (active.length === 0) return baseDataModel;
		const out: Record<string, unknown> = {};
		for (const [key, value] of Object.entries(baseDataModel)) {
			const rows =
				value && typeof value === 'object' && Array.isArray((value as { rows?: unknown }).rows)
					? ((value as { rows: Row[] }).rows)
					: null;
			if (rows === null) {
				out[key] = value;
				continue;
			}
			const applicable = active.filter(([column]) => rows.length === 0 || column in rows[0]);
			if (applicable.length === 0) {
				out[key] = value;
				continue;
			}
			const filtered = rows.filter((row) =>
				applicable.every(([column, values]) => values.includes(String(row[column]))),
			);
			out[key] = { ...(value as Record<string, unknown>), rows: filtered };
		}
		return out;
	});

	let sources = $derived(getDataSources(envelope.createSurface));
	let statuses = $state<Record<string, SourceUpdate>>({});

	// Svelte 5 rule: `setContext` must run at component INIT, never inside `$effect` — the lane
	// itself is only known once `sources` resolves (and is torn down/recreated on every envelope
	// change), so we set a stable PROXY once and let it forward to whichever lane is current.
	let lane: LinkedLane | undefined;
	const laneProxy: LinkedLane = {
		start: () => lane?.start(),
		stop: () => lane?.stop(),
		setParam: (source, name, value) => lane?.setParam(source, name, value) ?? Promise.resolve(),
		refreshAll: () => lane?.refreshAll() ?? Promise.resolve(),
	};
	setContext(LINKED_LANE_CONTEXT, laneProxy);

	const filterController: FilterController = {
		setFilter(column, values) {
			activeFilters = { ...activeFilters, [column]: values };
		},
		getFilter(column) {
			return activeFilters[column] ?? [];
		},
	};
	setContext(FILTER_CONTEXT, filterController);

	$effect(() => {
		if (!sources) {
			lane = undefined;
			statuses = {};
			return;
		}
		const created = createLinkedLane(sources, {
			baseUrl: querySourceBaseUrl,
			headers: querySourceHeaders,
			transformsBase: transformsBase ?? `${config.apiBaseUrl}/static/a2ui/transforms`,
			onUpdate: (u: SourceUpdate) => {
				if (u.rows !== null) {
					// S9/AC16: a source's rows always land as `dataModel[key] = {rows: [...]}` — the whole
					// value is replaced, mirroring the Python executor's `data_model_patch` exactly.
					baseDataModel = { ...baseDataModel, [u.key]: { rows: u.rows } };
				}
				statuses = { ...statuses, [u.key]: u };
			},
		});
		lane = created;
		created.start();
		return () => {
			created.stop();
			if (lane === created) lane = undefined;
		};
	});

	async function serverRefresh(): Promise<void> {
		if (!persistedSurfaceId) return;
		await fetch(`${config.apiBaseUrl}/api/v1/ui/surfaces/${persistedSurfaceId}/refresh`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
			body: JSON.stringify({ params: {} }),
		});
	}

	let sourceEntries = $derived(sources ? Object.entries(statuses) : []);
</script>

<div class="a2ui-surface">
	{#if !root}
		<div class="text-sm text-muted-foreground italic p-3">Unsupported surface</div>
	{:else if isInfographicLike}
		<A2UIInfographic component={root} {dataModel} />
	{:else}
		<A2UINode descriptor={{ component: root.component, properties: root }} {dataModel} />
	{/if}
	{#if sources}
		<div class="a2ui-linked-notices flex flex-col gap-1 mt-2">
			{#each sourceEntries as [key, status] (key)}
				{#if status.status === 'unavailable'}
					<p class="text-xs text-amber-600" data-testid="notice-unavailable-{key}">
						{key}: unavailable — data as of {status.snapshotAt ?? 'never'}
					</p>
				{:else if status.status === 'error'}
					<p class="text-xs text-destructive" data-testid="notice-error-{key}">
						{key}: could not load — data as of {status.snapshotAt ?? 'never'}
					</p>
				{:else if status.snapshotAt === null}
					<p class="text-xs text-muted-foreground italic" data-testid="notice-loading-{key}">
						Loading {key}…
					</p>
				{:else}
					<p class="text-xs text-muted-foreground" data-testid="notice-snapshot-{key}">
						{key}: data as of {status.snapshotAt}
					</p>
				{/if}
			{/each}
			{#if persistedSurfaceId}
				<button type="button" class="text-xs underline self-start" onclick={serverRefresh}>
					Refresh
				</button>
			{/if}
		</div>
	{/if}
</div>
