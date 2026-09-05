<script lang="ts">
	// ai-parrot (FEAT-527): root dispatcher for an A2UI v1.0 envelope —
	// `Infographic`/`Report` roots render via `A2UIInfographic` (title +
	// sections-as-tabs); anything else (a bare Chart/DataTable/KPICard/…
	// widget) renders via `A2UINode` directly. Gated behind `features.a2ui`
	// by the caller (`InfographicCanvas.svelte`, TASK-2868) — this component
	// itself has no gate of its own so it stays independently testable.
	import A2UIInfographic from './A2UIInfographic.svelte';
	import A2UINode from './A2UINode.svelte';
	import type { A2UIEnvelope, WireComponent } from './a2ui-types';

	let { envelope }: { envelope: A2UIEnvelope } = $props();

	let root = $derived<WireComponent | undefined>(
		envelope.createSurface.components.find((c) => c.id === 'root') ??
			envelope.createSurface.components[0],
	);
	let dataModel = $derived(envelope.createSurface.dataModel ?? {});
	let isInfographicLike = $derived(
		root !== undefined && (root.component === 'Infographic' || root.component === 'Report'),
	);
</script>

<div class="a2ui-surface">
	{#if !root}
		<div class="text-sm text-muted-foreground italic p-3">Unsupported surface</div>
	{:else if isInfographicLike}
		<A2UIInfographic component={root} {dataModel} />
	{:else}
		<A2UINode descriptor={{ component: root.component, properties: root }} {dataModel} />
	{/if}
</div>
