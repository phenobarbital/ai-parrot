<script lang="ts">
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import type { DockState, DockNode, DockPane } from './dock/types';
	import DockSplitter from './DockSplitter.svelte';
	import { onMount, tick } from 'svelte';
	import { v4 as uuidv4 } from 'uuid';

	let { dashboard } = $props<{ dashboard: Dashboard }>();

	// Initialize state if empty
	let dockState = $state<DockState>({ rootId: '', nodes: {}, panes: {} });
	let initialized = $state(false);

	$effect(() => {
		// Load from dashboard or init default
		const saved = dashboard.savedLayouts?.dock;
		if (saved && saved.rootId) {
			dockState = saved as DockState;
		} else if (!initialized) {
			// Create default single pane
			const rootId = uuidv4();
			const paneId = uuidv4();

			dockState = {
				rootId,
				nodes: {
					[rootId]: { id: rootId, type: 'pane', children: [], paneId, size: 100 }
				},
				panes: {
					[paneId]: { id: paneId, widgets: [], activeWidgetId: null }
				}
			};

			// Distribute existing widgets to the first pane
			const allWidgets = dashboard.widgets.map((w) => w.id);
			if (allWidgets.length > 0) {
				dockState.panes[paneId].widgets = allWidgets;
				dockState.panes[paneId].activeWidgetId = allWidgets[0];
			}

			save();
		}
		initialized = true;
	});

	function save() {
		dashboard.savedLayouts.dock = $state.snapshot(dockState);
		dashboard.save();
	}

	function handleSplit(e: CustomEvent<{ paneId: string; direction: 'horizontal' | 'vertical' }>) {
		const { paneId, direction } = e.detail;

		// Find node for this pane
		const nodeId = Object.keys(dockState.nodes).find((k) => dockState.nodes[k].paneId === paneId);
		if (!nodeId) return;

		const node = dockState.nodes[nodeId];
		const newPaneId = uuidv4();
		const newNodeId = uuidv4();

		// Create new pane
		dockState.panes[newPaneId] = { id: newPaneId, widgets: [], activeWidgetId: null };

		// Create new node structure
		const originalPaneId = node.paneId!;
		delete node.paneId;

		node.type = direction === 'horizontal' ? 'row' : 'col';

		const child1Id = uuidv4();
		const child2Id = uuidv4();

		dockState.nodes[child1Id] = {
			id: child1Id,
			type: 'pane',
			children: [],
			paneId: originalPaneId,
			size: 50
		};
		dockState.nodes[child2Id] = {
			id: child2Id,
			type: 'pane',
			children: [],
			paneId: newPaneId,
			size: 50
		};

		node.children = [child1Id, child2Id];

		save();
	}

	function handleDrop(e: CustomEvent<{ wId: string; targetPaneId: string }>) {
		const { wId, targetPaneId } = e.detail;

		// Remove from all other panes
		for (const pid of Object.keys(dockState.panes)) {
			const p = dockState.panes[pid];
			const idx = p.widgets.indexOf(wId);
			if (idx !== -1) {
				p.widgets.splice(idx, 1);
				if (p.activeWidgetId === wId) p.activeWidgetId = p.widgets[0] || null;
			}
		}

		// Add to target
		const target = dockState.panes[targetPaneId];
		if (target) {
			target.widgets.push(wId);
			target.activeWidgetId = wId;
		}

		save();
	}

	function handleCustomSplit(
		e: CustomEvent<{ paneId: string; direction: 'horizontal' | 'vertical' }>
	) {
		// Forward to our existing logic
		handleSplit({ detail: e.detail } as any);
	}
</script>

<div
	class="bg-base-200 h-full w-full p-1"
	ondock-drop={handleDrop}
	ondock-split={handleCustomSplit}
>
	{#if dockState.rootId && dockState.nodes[dockState.rootId]}
		<DockSplitter nodeId={dockState.rootId} {dockState} {dashboard} on:split={handleSplit} />
	{/if}
</div>
