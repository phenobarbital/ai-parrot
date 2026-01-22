<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { DashboardContainer } from '$lib/dashboards/dashboard';
	import '$lib/dashboards/styles.css';
	import '$lib/dashboards/dashboard.css';

	export let options: any = {};

	let containerEl: HTMLElement;
	let dashboardContainer: DashboardContainer;
	let themeObserver: MutationObserver | null = null;
	let currentTheme = '';

	function updateTheme() {
		if (!containerEl) return;
		const theme = document.documentElement.getAttribute('data-theme') || 'light';
		if (theme !== currentTheme) {
			currentTheme = theme;
			// Force CSS re-evaluation by updating a data attribute
			containerEl.setAttribute('data-dashboard-theme', theme);
		}
	}

	onMount(() => {
		if (containerEl) {
			dashboardContainer = new DashboardContainer(containerEl, options.id);

			// Initialize theme
			updateTheme();

			// Watch for theme changes on document root
			themeObserver = new MutationObserver((mutations) => {
				for (const mutation of mutations) {
					if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
						updateTheme();
					}
				}
			});

			themeObserver.observe(document.documentElement, {
				attributes: true,
				attributeFilter: ['data-theme']
			});
		}
	});

	onDestroy(() => {
		themeObserver?.disconnect();
		dashboardContainer?.destroy();
	});

	export function getContainer() {
		return dashboardContainer;
	}
</script>

<div
	class="dashboard-wrapper bg-base-200 text-base-content h-full w-full"
	bind:this={containerEl}
	data-dashboard-theme={currentTheme}
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
