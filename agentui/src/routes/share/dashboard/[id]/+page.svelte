<script lang="ts">
	import { page } from '$app/stores';
	import DashboardContainerWrapper from '$lib/components/dashboard/DashboardContainerWrapper.svelte';
	import DashboardViewWrapper from '$lib/components/dashboard/DashboardViewWrapper.svelte';
	import { checkPermission } from '$lib/dashboards/permissions';
	import { onMount } from 'svelte';

	$: id = $page.params.id;

	let hasPermission = false;
	let loading = true;
	let error = '';

	onMount(async () => {
		try {
			hasPermission = await checkPermission('dashboard', id);
		} catch (e) {
			error = 'Failed to verify permissions';
		} finally {
			loading = false;
		}
	});
</script>

<div class="h-full w-full">
	{#if loading}
		<div class="p-4">Loading...</div>
	{:else if error}
		<div class="p-4 text-red-500">{error}</div>
	{:else if !hasPermission}
		<div class="p-4 text-red-500">Access Denied</div>
	{:else}
		<!-- 
       The user asked for "each dashboard-container requires own url".
       "share/dashboard/{dashboard_id}"
       This probably implies showing just that dashboard/tab, or the container with that active?
       "each dashboard tab requires own URL... http://localhost:5173/share/dashboard/{dashboard_id}"
       
       If dashboard_id refers to a specific view (tab) ID, we should render DashboardViewWrapper.
       If it refers to a container, we render Container.
       
       Given the context "Dashboard: a container with several tabs", and user saying "Dashboard as Svelte Component... each dashboard-container requires own url".
       But later "Dashboard as Svelte Component... each dashboard tab requires own URL".
       
       And "http://localhost:5173/share/dashboard/{dashboard_id}".
       
       I'll assume reasonable default: If it's a shared *dashboard*, it's likely a specific view/tab they want to share.
       So I will use DashboardViewWrapper.
     -->
		<DashboardViewWrapper {id} />
	{/if}
</div>
