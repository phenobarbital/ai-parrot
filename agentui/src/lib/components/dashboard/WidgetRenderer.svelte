<script lang="ts">
	import type { Widget } from '$lib/stores/dashboard/widget.svelte';
	import { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';
	import AgentWidgetView from './widgets/AgentWidgetView.svelte';

	let { widget } = $props<{ widget: Widget }>();

	function getComponent(w: Widget) {
		if (w instanceof AgentWidget) return AgentWidgetView;
		return null;
	}

	const Component = $derived(getComponent(widget));
</script>

{#if Component}
	<Component {widget} />
{:else}
	<div class="text-base-content/50 flex h-full items-center justify-center p-4">
		{widget.type} widget placeholder
	</div>
{/if}
