<script lang="ts">
	import { workspace } from '$lib/stores/dashboard/workspace.svelte';
	import DashboardTabs from './DashboardTabs.svelte';
	import DashboardCanvas from './DashboardCanvas.svelte';
	import AddWidgetModal from './modals/AddWidgetModal.svelte';
	import DashboardSettingsModal from './modals/DashboardSettingsModal.svelte';
	import { registerDefaultWidgets } from '$lib/stores/dashboard/registerDefaults';
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';

	// Auto-create dashboard if none exists on mount
	import { onMount } from 'svelte';

	onMount(async () => {
		registerDefaultWidgets();
		if (!workspace.isLoading && workspace.dashboards.length === 0) {
			await workspace.addDashboard('Main Dashboard');
		}
	});

	let activeDash = $derived(workspace.activeDashboard);

	// Modal State
	let showAddWidget = $state(false);
	let showSettings = $state(false);
	let targetDash = $state<Dashboard | null>(null);

	// Direct handlers for clearer binding
	function onRename(e: CustomEvent<Dashboard>) {
		targetDash = e.detail;
		showSettings = true; // For now open settings? Or specific rename prompt?
		// User requested inline or specific. Settings has general tab with rename.
	}

	function onAddWidget(e: CustomEvent<Dashboard>) {
		targetDash = e.detail;
		showAddWidget = true;
	}

	function onSettings(e: CustomEvent<Dashboard>) {
		targetDash = e.detail;
		showSettings = true;
	}
</script>

<div class="bg-base-100 flex h-full w-full flex-col overflow-hidden">
	<DashboardTabs on:rename={onRename} on:addWidget={onAddWidget} on:settings={onSettings} />

	<div class="relative flex-1 overflow-hidden">
		{#if workspace.isLoading}
			<div class="absolute inset-0 flex items-center justify-center">
				<span class="loading loading-spinner loading-lg"></span>
			</div>
		{:else if activeDash}
			<DashboardCanvas dashboard={activeDash} />
		{:else}
			<div class="text-base-content/50 flex h-full items-center justify-center">
				No active dashboard selected
			</div>
		{/if}
	</div>

	{#if activeDash || targetDash}
		<AddWidgetModal dashboard={targetDash || activeDash!} bind:isOpen={showAddWidget} />
		<DashboardSettingsModal dashboard={targetDash || activeDash!} bind:isOpen={showSettings} />
	{/if}
</div>
