<script lang="ts">
	import { page } from '$app/stores';
	import { tick } from 'svelte';
	import type { Program, Module, Submodule } from '$lib/types';
	import { getModuleBySlug, getSubmoduleBySlug } from '$lib/data/mock-data';
	import CrewBuilder from '$lib/components/modules/CrewBuilder/index.svelte';
	import DashboardContainerWrapper from '$lib/components/dashboard/DashboardContainerWrapper.svelte';

	const program = $derived($page.data.program as Program);
	const moduleSlug = $derived($page.params.module);
	const submoduleSlug = $derived($page.params.submodule);

	const module = $derived.by(() => {
		if (program && moduleSlug) {
			return getModuleBySlug(program, moduleSlug);
		}
		return null;
	});

	const submodule = $derived.by(() => {
		if (module && submoduleSlug) {
			return getSubmoduleBySlug(module, submoduleSlug);
		}
		return null;
	});

	// Breadcrumb items
	const breadcrumbs = $derived([
		{ label: program?.name || 'Program', href: `/program/${program?.slug}` },
		{ label: module?.name || 'Module', href: `/program/${program?.slug}/${module?.slug}` },
		{ label: submodule?.name || 'Submodule', href: '#', current: true }
	]);

	// Dashboard container reference
	let dashboardContainer: DashboardContainerWrapper;

	// Initialize dashboard with sample widgets when container type
	$effect(() => {
		if (submodule?.type === 'container' && dashboardContainer) {
			tick().then(() => setTimeout(() => initDashboard(), 100));
		}
	});

	async function initDashboard() {
		const container = dashboardContainer?.getContainer();
		if (!container) return;

		// Only create demo if no dashboards exist
		if (container.getAllDashboards().length > 0) return;

		const dashId = submodule?.id || 'default';

		// Tab 1: Overview with Grid Layout
		const d1 = container.addDashboard(
			{ id: `${dashId}-overview`, title: 'Overview', icon: '📊' },
			{ layoutMode: 'grid' }
		);

		// Add sample widgets
		try {
			const { CardWidget } = await import('$lib/dashboards/card-widget.js');
			const card1 = new CardWidget({ title: 'Total Items' });
			d1.addWidget(card1, { row: 0, col: 0, rowSpan: 4, colSpan: 4 });

			const card2 = new CardWidget({ title: 'Low Stock Alerts' });
			d1.addWidget(card2, { row: 0, col: 4, rowSpan: 4, colSpan: 4 });
		} catch (e) {
			console.warn('CardWidget not available:', e);
		}

		// Tab 2: Details with Free Layout
		container.addDashboard(
			{ id: `${dashId}-details`, title: 'Details', icon: '📋' },
			{ layoutMode: 'free' }
		);

		// Activate first tab
		container.activate(`${dashId}-overview`);
	}
</script>

<div class="flex h-full flex-col">
	<!-- Breadcrumb -->
	<div class="mb-2">
		<nav class="breadcrumbs text-sm">
			<ul>
				{#each breadcrumbs as crumb, i}
					<li>
						{#if crumb.current}
							<span class="text-base-content font-medium">{crumb.label}</span>
						{:else}
							<a
								href={crumb.href}
								class="text-base-content/60 hover:text-primary transition-colors"
							>
								{crumb.label}
							</a>
						{/if}
					</li>
				{/each}
			</ul>
		</nav>
		<h1 class="mt-2 text-2xl font-bold">{submodule?.name}</h1>
		{#if submodule?.description}
			<p class="text-base-content/60 mt-1">{submodule.description}</p>
		{/if}
	</div>

	<!-- Content Area -->
	<div
		class="bg-base-100 border-base-content/5 relative flex-1 overflow-hidden rounded-xl border shadow-sm"
	>
		{#if program?.slug === 'crewbuilder'}
			<div class="absolute inset-0">
				<CrewBuilder moduleData={submodule} />
			</div>
		{:else if submodule?.type === 'container'}
			<!-- Dashboard Container -->
			<div class="absolute inset-0">
				<DashboardContainerWrapper
					bind:this={dashboardContainer}
					options={{ id: `dashboard-${submodule.id}` }}
				/>
			</div>
		{:else}
			<!-- Dashboard Module Placeholder -->
			<div class="flex h-full flex-col items-center justify-center text-center">
				<div class="bg-base-200 mb-6 flex h-24 w-24 items-center justify-center rounded-3xl">
					<svg
						class="text-base-content/30 h-12 w-12"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
						></path>
					</svg>
				</div>
				<h2 class="mb-2 text-xl font-semibold">Full-Screen Module</h2>
				<p class="text-base-content/60 max-w-md">
					This is a <span class="badge badge-outline">module</span> submodule. Custom Svelte components
					will be rendered here full-screen.
				</p>
				<div class="mt-6">
					<div class="badge badge-ghost">Component: Coming Soon</div>
				</div>
			</div>
		{/if}
	</div>
</div>
