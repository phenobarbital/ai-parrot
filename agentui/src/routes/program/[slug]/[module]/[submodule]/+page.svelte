<script lang="ts">
	import { page } from '$app/stores';
	import { tick } from 'svelte';
	import type { Program, Module, Submodule } from '$lib/types';
	import { getModuleBySlug, getSubmoduleBySlug } from '$lib/data/mock-data';
	import CrewBuilder from '$lib/components/modules/CrewBuilder/index.svelte';
	import DashboardContainerWrapper from '$lib/components/dashboard/DashboardContainerWrapper.svelte';
	import type { ComponentType } from 'svelte';

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
	let dashboardContainer = $state<DashboardContainerWrapper>();

	// track if dashboard is enabled for 'module' type submodules
	let moduleEnabled = $state(false);

	const componentModules = import.meta.glob('/src/lib/components/**/*.svelte');
	let moduleComponent = $state<ComponentType | null>(null);
	let moduleComponentProps = $state<Record<string, unknown>>({});
	let componentLoadId = 0;

	function normalizeComponentParameters(parameters?: Record<string, unknown>) {
		if (!parameters) return {};
		const normalized: Record<string, unknown> = { ...parameters };
		for (const [key, value] of Object.entries(parameters)) {
			const camelKey = key.includes('_') ? key.replace(/_([a-z])/g, (_, c) => c.toUpperCase()) : key;
			if (!(camelKey in normalized)) {
				normalized[camelKey] = value;
			}
		}
		return normalized;
	}

	$effect(() => {
		if (submodule?.id) {
			moduleEnabled = localStorage.getItem(`dashboard-enabled-${submodule.id}`) === 'true';
		}
	});

	function enableDashboard() {
		if (submodule?.id) {
			moduleEnabled = true;
			localStorage.setItem(`dashboard-enabled-${submodule.id}`, 'true');
		}
	}

	// Initialize dashboard with sample widgets when container type or enabled
	$effect(() => {
		if ((submodule?.type === 'container' || moduleEnabled) && dashboardContainer) {
			tick().then(() => setTimeout(() => initDashboard(), 100));
		}
	});

	$effect(() => {
		const isComponentType = submodule?.type === 'component';
		const componentPath = submodule?.path;
		if (!isComponentType || !componentPath) {
			moduleComponent = null;
			moduleComponentProps = {};
			return;
		}

		const currentLoad = ++componentLoadId;
		moduleComponentProps = normalizeComponentParameters(submodule?.parameters);

		const importPath = `/src/lib/components/${componentPath}`;
		const loader = componentModules[importPath];
		if (!loader) {
			moduleComponent = null;
			return;
		}

		loader()
			.then((mod) => {
				if (currentLoad === componentLoadId) {
					moduleComponent = mod.default as ComponentType;
				}
			})
			.catch((error) => {
				console.error('Failed to load module component:', error);
				if (currentLoad === componentLoadId) {
					moduleComponent = null;
				}
			});
	});

	async function initDashboard() {
		const container = dashboardContainer?.getContainer();
		if (!container) return;

		// Try to load from localStorage first
		if (container.loadState()) return;

		// Only create demo if no dashboards exist and no state was loaded
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
		{:else if submodule?.type === 'container' || moduleEnabled}
			<!-- Dashboard Container -->
			<div class="absolute inset-0">
				{#key submodule.id}
					<DashboardContainerWrapper
						bind:this={dashboardContainer}
						options={{ id: `dashboard-${submodule.id}` }}
					/>
				{/key}
			</div>
		{:else if submodule?.type === 'component' && submodule?.path}
			<div class="absolute inset-0">
				{#if moduleComponent}
					{@const Component = moduleComponent}
					<Component {...moduleComponentProps} />
				{:else}
					<div class="flex h-full items-center justify-center text-center text-sm text-base-content/60">
						Unable to load component: {submodule.path}
					</div>
				{/if}
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
					{#if submodule?.type === 'module'}
						<button class="btn btn-primary" onclick={enableDashboard}>
							<svg class="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M12 4v16m8-8H4"
								/>
							</svg>
							Enable Dashboard Container
						</button>
					{:else}
						<div class="badge badge-ghost">Component: Coming Soon</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
