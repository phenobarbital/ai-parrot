<script lang="ts">
	import type { DashboardModel } from '$lib/stores/dashboard/store.svelte';
	import WidgetShell from './WidgetShell.svelte';
	import AgentWidgetView from './widgets/AgentWidgetView.svelte';
	import { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';

	let { model } = $props<{ model: DashboardModel }>();

	// Grid CSS vars for the container
	let containerStyle = $derived.by(() => {
		if (model.layoutMode === 'grid') {
			return `
                display: grid;
                grid-template-columns: repeat(${model.gridConfig.cols}, 1fr);
                grid-auto-rows: ${model.gridConfig.rowHeight}px;
                gap: ${model.gridConfig.gap}px;
                width: 100%;
                padding: 16px;
            `;
		}

		if (model.layoutMode === 'free') {
			return `
                position: relative;
                width: 100%;
                height: 100%;
                overflow: auto;
            `;
		}

		// Dock mode logic...
		return `
            display: flex;
            width: 100%;
            height: 100%;
        `;
	});

	// Helper to resolve component type
	function getComponent(widget: any) {
		if (widget instanceof AgentWidget) {
			return AgentWidgetView;
		}
		// Fallback or other types map here
		return null;
	}

	function handleClose(id: string) {
		model.removeWidget(id);
	}

	let containerWidth = $state(0);
</script>

<div
	class="bg-base-200/50 dashboard-area h-full w-full overflow-y-auto"
	bind:clientWidth={containerWidth}
>
	<div style={containerStyle} class:relative={true}>
		{#each model.widgets as widget (widget.id)}
			{@const Component = getComponent(widget)}
			<WidgetShell
				{widget}
				gridConfig={model.gridConfig}
				{containerWidth}
				on:close={() => handleClose(widget.id)}
			>
				{#if Component}
					<Component {widget} />
				{:else}
					<div class="text-error p-4">Unknown widget type: {widget.type}</div>
				{/if}
			</WidgetShell>
		{/each}
	</div>
</div>
