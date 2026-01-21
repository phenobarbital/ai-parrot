<script lang="ts">
	import { page } from '$app/stores';
	import WidgetWrapper from '$lib/components/dashboard/WidgetWrapper.svelte';
	import { checkPermission } from '$lib/dashboards/permissions';
	import { onMount } from 'svelte';
	import { Widget } from '$lib/dashboards/widget';

	$: id = $page.params.id;

	let hasPermission = false;
	let loading = true;
	let error = '';

	onMount(async () => {
		try {
			hasPermission = await checkPermission('widget', id);
		} catch (e) {
			error = 'Failed to verify permissions';
		} finally {
			loading = false;
		}
	});

	async function createWidget(): Promise<Widget> {
		// In a real implementation we would fetch the widget configuration by ID
		// and instantiate the correct widget class.
		// For now, let's create a placeholder or try to find it.

		const { HTMLWidget } = await import('$lib/dashboards/html-widget.js');
		const w = new HTMLWidget({ title: 'Shared Widget ' + id });
		w.el.innerHTML = `<div style="padding: 20px;">Shared Content for Widget ${id}</div>`;
		return w;
	}
</script>

<div class="h-full w-full">
	{#if loading}
		<div class="p-4">Loading...</div>
	{:else if error}
		<div class="p-4 text-red-500">{error}</div>
	{:else if !hasPermission}
		<div class="p-4 text-red-500">Access Denied</div>
	{:else}
		<WidgetWrapper {createWidget} />
	{/if}
</div>
