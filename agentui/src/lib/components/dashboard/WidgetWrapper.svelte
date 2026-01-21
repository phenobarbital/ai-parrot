<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { Widget } from '$lib/dashboards/widget';
	// We need a way to instantiate specific widgets based on type, or receive the widget instance
	// For shared view, we likely fetch config and instantiate.
	// For now, let's assume we pass a factory or config.
	import '$lib/dashboards/dashboard.css';

	export let createWidget: () => Promise<Widget>;

	let containerEl: HTMLElement;
	let widget: Widget;

	onMount(async () => {
		if (containerEl && createWidget) {
			try {
				widget = await createWidget();
				if (widget) {
					containerEl.appendChild(widget.el);
					// Widgets usually expect to be in a grid/layout, but for standalone view we might need to adjust styles
					widget.el.style.position = 'relative';
					widget.el.style.width = '100%';
					widget.el.style.height = '100%';
					widget.el.style.left = '0';
					widget.el.style.top = '0';
				}
			} catch (err) {
				console.error('Failed to create widget', err);
			}
		}
	});

	onDestroy(() => {
		// if (widget && widget.destroy) widget.destroy(); // Widget.destroy might need to be called
	});
</script>

<div class="widget-wrapper h-full w-full" bind:this={containerEl}></div>

<style>
	.widget-wrapper {
		width: 100%;
		height: 100vh;
		overflow: hidden;
		background: #fff; /* or theme bg */
	}
</style>
