<script lang="ts">
	import { page } from '$app/stores';
	import type { Program, Module, Submodule } from '$lib/types';
	import { getModuleBySlug, getSubmoduleBySlug } from '$lib/data/mock-data';
	import CrewBuilder from '$lib/components/modules/CrewBuilder/index.svelte';

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
</script>

<div class="flex h-full flex-col">
	<!-- Breadcrumb -->
	<div class="mb-6">
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
		class="bg-base-100 border-base-content/5 relative flex-1 overflow-hidden rounded-2xl border p-6 shadow-sm"
	>
		{#if program?.slug === 'crewbuilder'}
			<div class="absolute inset-0">
				<CrewBuilder moduleData={submodule} />
			</div>
		{:else if submodule?.type === 'container'}
			<!-- Dashboard Container Placeholder -->
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
							d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
						></path>
					</svg>
				</div>
				<h2 class="mb-2 text-xl font-semibold">Dashboard Container</h2>
				<p class="text-base-content/60 max-w-md">
					This is a <span class="badge badge-outline">container</span> submodule. Dashboards with tabs
					and widgets will be rendered here.
				</p>
				<div class="mt-6 flex gap-2">
					<div class="badge badge-ghost">Tabs: Coming Soon</div>
					<div class="badge badge-ghost">Widgets: Coming Soon</div>
				</div>
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
