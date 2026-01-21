<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { DashboardView, GridLayout, FreeLayout, DockLayout } from '$lib/dashboards/dashboard';
	import type { DashboardViewOptions } from '$lib/dashboards/types';
	import '$lib/dashboards/dashboard.css';

	export let id: string;
	export let title: string = 'Dashboard';
	export let icon: string = '📊';
	export let layoutMode: 'grid' | 'free' | 'dock' = 'grid';
	export let options: DashboardViewOptions = {};

	let viewEl: HTMLElement;
	let dashboardView: DashboardView;

	onMount(() => {
		if (viewEl) {
			// DashboardView expects to be part of a container usually, or at least standalone-ish
			// The current DashboardView constructor creates elements but doesn't mount itself unless added to container.
			// We might need to adjust DashboardView to be mountable directly or simulate it.

			// However, DashboardView logic heavily relies on creating its own elements.
			// Let's instantiate it and append its element to our wrapper.

			// Note: DashboardView constructor signature:
			// constructor(id: string, title: string, icon: string, opts: DashboardViewOptions)

			const opts = { ...options, layoutMode };
			dashboardView = new DashboardView(id, title, icon, opts);

			// Append the dashboard element to our Svelte container
			viewEl.appendChild(dashboardView.el);

			// Trigger resize if needed
			// window.dispatchEvent(new Event('resize'));
		}
	});

	onDestroy(() => {
		if (dashboardView) {
			dashboardView.destroy();
		}
	});
</script>

<div class="dashboard-view-wrapper h-full w-full" bind:this={viewEl}></div>

<style>
	.dashboard-view-wrapper {
		width: 100%;
		height: 100%;
		overflow: hidden;
		position: relative;
	}

	/* Ensure dashboard view takes full height */
	:global(.dashboard-view) {
		height: 100% !important;
		display: flex;
		flex-direction: column;
	}

	:global(.dashboard-main) {
		flex: 1;
		overflow: hidden;
		position: relative;
	}
</style>
