<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { DashboardContainer } from '$lib/dashboards/dashboard';
	import '$lib/dashboards/styles.css';
	import '$lib/dashboards/dashboard.css';

	export let options: any = {};

	let containerEl: HTMLElement;
	let dashboardContainer: DashboardContainer;

	onMount(() => {
		if (containerEl) {
			dashboardContainer = new DashboardContainer(containerEl);
			// Initialize with options if provided logic exists or extended
		}
	});

	onDestroy(() => {
		// dashboardContainer?.destroy(); // If destroy method exists on container
	});
	export function getContainer() {
		return dashboardContainer;
	}
</script>

<div
	class="dashboard-wrapper bg-base-200 text-base-content h-full w-full"
	bind:this={containerEl}
></div>

<style>
	.dashboard-wrapper {
		display: flex;
		flex-direction: column;
		height: 100%;
		width: 100%;
		overflow: hidden;
	}
</style>
