<script lang="ts">
	import { page } from '$app/stores';
	import DashboardContainerWrapper from '$lib/components/dashboard/DashboardContainerWrapper.svelte';
	import { onMount, tick } from 'svelte';

	// Params from URL
	$: program = $page.params.program;
	$: module_name = $page.params.module;
	$: submodule = $page.params.submodule;
	$: dashboardConfig = $page.params.dashboardId; // "123" or "123-tab1"

	let containerComponent: DashboardContainerWrapper;

	onMount(async () => {
		// Small delay to ensure container is ready
		await tick();
		setTimeout(() => initDemo(), 100);
	});

	async function initDemo() {
		const container = containerComponent?.getContainer();
		if (!container) return;

		const dashId = dashboardConfig.split('-tab')[0] || 'default';
		const tabSuffix = dashboardConfig.split('-tab')[1];

		// Create a demo dashboard if none exists
		if (container.getAllDashboards().length === 0) {
			console.log('Creating demo dashboards...');

			// Tab 1: Grid Layout
			const d1 = container.addDashboard(
				{
					id: dashId + '-tab1',
					title: 'Sales Report',
					icon: '💰'
				},
				{ layoutMode: 'grid' }
			);

			// Add some widgets to D1
			try {
				const { CardWidget } = await import('$lib/dashboards/card-widget.js');
				const card1 = new CardWidget({ title: 'Revenue' });
				d1.addWidget(card1, { row: 0, col: 0, rowSpan: 4, colSpan: 4 });
			} catch (e) {
				console.warn('CardWidget not available:', e);
			}

			// Tab 2: Free Layout
			const d2 = container.addDashboard(
				{
					id: dashId + '-tab2',
					title: 'Free Canvas',
					icon: '🎨'
				},
				{ layoutMode: 'free' }
			);

			// Add widget to Free Canvas
			try {
				const { HTMLWidget } = await import('$lib/dashboards/html-widget.js');
				const freeWidget = new HTMLWidget({ title: 'Notes', icon: '📝' });
				freeWidget.el.innerHTML =
					'<div style="padding: 20px;"><h3>Free Layout Widget</h3><p>Drag me around!</p></div>';
				d2.addWidget(freeWidget, { x: 50, y: 50, width: 300, height: 200 });
			} catch (e) {
				console.warn('HTMLWidget not available for Free Canvas:', e);
			}

			// Tab 3: Dock Layout
			const d3 = container.addDashboard(
				{
					id: dashId + '-tab3',
					title: 'Terminal',
					icon: '🖥️'
				},
				{ layoutMode: 'dock' }
			);

			// Add widgets to Dock Layout
			try {
				const { HTMLWidget } = await import('$lib/dashboards/html-widget.js');
				const dockWidget1 = new HTMLWidget({ title: 'Console', icon: '💻' });
				dockWidget1.el.innerHTML =
					'<div style="padding: 10px; background: #1e1e1e; color: #0f0; font-family: monospace; height: 100%;">$ Welcome to Terminal<br/>$ _</div>';
				d3.addWidget(dockWidget1, { dockPosition: 'left' });

				const dockWidget2 = new HTMLWidget({ title: 'Output', icon: '📄' });
				dockWidget2.el.innerHTML = '<div style="padding: 10px;">Output panel content here.</div>';
				d3.addWidget(dockWidget2, { dockPosition: 'right' });
			} catch (e) {
				console.warn('HTMLWidget not available for Dock Layout:', e);
			}
		}

		if (tabSuffix) {
			// Activate specific tab if requested
			const targetId = dashId + '-tab' + tabSuffix;
			container.activate(targetId);
		} else {
			// Default to first active or first in list
			const all = container.getAllDashboards();
			if (all.length > 0 && !container.getActiveDashboard()) {
				container.activate(all[0].id);
			}
		}
	}
</script>

<div class="flex h-full w-full flex-col">
	<div class="border-b bg-gray-50 p-2">
		<h1 class="breadcrumbs text-sm font-semibold text-gray-500">
			{program} / {module_name} / {submodule} / Dashboard {dashboardConfig}
		</h1>
	</div>

	<div class="relative flex-1 overflow-hidden">
		<DashboardContainerWrapper bind:this={containerComponent} />
	</div>
</div>

<style>
	.breadcrumbs {
		text-transform: capitalize;
	}
</style>
