<script lang="ts">
	import type { DockState } from './types';
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import WidgetRenderer from '../../WidgetRenderer.svelte';
	import { createEventDispatcher } from 'svelte';
	import { workspace } from '$lib/stores/dashboard/workspace.svelte';

	let { paneId, dockState, dashboard } = $props<{
		paneId: string;
		dockState: DockState;
		dashboard: Dashboard;
	}>();

	const dispatch = createEventDispatcher();

	let pane = $derived(dockState.panes[paneId]);
	let activeWidgetId = $derived(pane?.activeWidgetId);
	let activeWidget = $derived(
		activeWidgetId ? dashboard.widgets.find((w) => w.id === activeWidgetId) : null
	);

	function activate(wId: string) {
		if (pane) {
			pane.activeWidgetId = wId;
			save();
		}
	}

	function closeWidget(e: Event, wId: string) {
		e.stopPropagation();
		if (!pane) return;

		const idx = pane.widgets.indexOf(wId);
		if (idx !== -1) {
			pane.widgets.splice(idx, 1);
			if (pane.activeWidgetId === wId) {
				pane.activeWidgetId = pane.widgets[0] || null;
			}
			save();
		}
	}

	function split(direction: 'horizontal' | 'vertical') {
		dispatch('split', { paneId, direction }); // Needs to bubble up to Layout
		// Svelte 5 bubbling: we can use a callback or context, but dispatch works if forwarded.
		// Actually, bubbling custom events in Svelte 5 is component-based.
		// Let's assume DockLayout passed a context or we use a store action.
		// For now, let's emit a global event or assume specific binding.
		// We'll dispatch a native custom event that bubbles.
		const ev = new CustomEvent('dock-split', {
			bubbles: true,
			detail: { paneId, direction }
		});
		// Element ref needed? We can stick to standard dispatch but DockSplitter needs to forward it.
	}

	function save() {
		dashboard.save();
	}

	// Drop Logic
	let isDragOver = $state(false);

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		isDragOver = false;
		// Logic to move widget to this pane
		// Use a global "draggedWidget" store or dataTransfer?
		// Let's use simple dataTransfer for widget ID.
		const wId = e.dataTransfer?.getData('widget-id');
		if (wId && pane && !pane.widgets.includes(wId)) {
			// Remove from other panes
			// Accessing global dockState for clean up is tricky here without a method.
			// We should centralize this operation in DockLayout.

			// Emit event
			const ev = new CustomEvent('dock-drop', {
				bubbles: true,
				detail: { wId, targetPaneId: paneId }
			});
			e.target?.dispatchEvent(ev);
		}
	}
</script>

<div
	class="flex h-full w-full flex-col"
	ondragover={(e) => {
		e.preventDefault();
		isDragOver = true;
	}}
	ondragleave={() => (isDragOver = false)}
	ondrop={handleDrop}
	role="region"
>
	<!-- Tab Bar -->
	<div
		class="bg-base-200 no-scrollbar flex min-h-[32px] items-center overflow-x-auto border-b px-1"
	>
		{#if pane}
			{#each pane.widgets as wId}
				{@const w = dashboard.widgets.find((x) => x.id === wId)}
				{#if w}
					<button
						class="border-base-300 hover:bg-base-100 flex items-center gap-1 border-r px-2 py-1 text-xs transition-colors"
						class:bg-base-100={activeWidgetId === wId}
						class:font-bold={activeWidgetId === wId}
						onclick={() => activate(wId)}
						draggable="true"
						ondragstart={(e) => {
							e.dataTransfer?.setData('widget-id', wId);
						}}
					>
						<span>{w.title}</span>
						<span class="hover:text-error ml-1 cursor-pointer" onclick={(e) => closeWidget(e, wId)}
							>×</span
						>
					</button>
				{/if}
			{/each}
		{/if}

		<div class="flex-1"></div>

		<!-- Pane Actions -->
		<div class="dropdown dropdown-end">
			<div tabindex="0" role="button" class="btn btn-xs btn-ghost btn-square">⋮</div>
			<ul tabindex="0" class="dropdown-content menu bg-base-100 rounded-box z-[1] w-40 p-2 shadow">
				<li><button onclick={() => split('horizontal')}>Split Horizontal</button></li>
				<li><button onclick={() => split('vertical')}>Split Vertical</button></li>
			</ul>
		</div>
	</div>

	<!-- Content -->
	<div class="bg-base-100 relative flex-1 overflow-hidden">
		{#if activeWidget}
			<WidgetRenderer widget={activeWidget} />
		{:else}
			<div class="text-base-content/30 flex h-full items-center justify-center text-xs">
				Empty Pane
			</div>
		{/if}

		{#if isDragOver}
			<div
				class="bg-primary/10 border-primary pointer-events-none absolute inset-0 flex items-center justify-center border-2 border-dashed"
			>
				<span class="text-primary font-bold">Drop Here</span>
			</div>
		{/if}
	</div>
</div>
