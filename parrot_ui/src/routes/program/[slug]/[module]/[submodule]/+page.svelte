<script lang="ts">
	import { page } from '$app/stores';
	import type { Program, Module, Submodule } from '$lib/types';
	import { getModuleBySlug, getSubmoduleBySlug } from '$lib/data/mock-data';
	import CrewBuilder from '$lib/components/modules/CrewBuilder/index.svelte';
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

	const componentModules = import.meta.glob('/src/lib/components/**/*.svelte');
	let moduleComponent = $state<ComponentType | null>(null);
	let moduleComponentProps = $state<Record<string, unknown>>({});
	let componentLoadId = 0;

	function normalizeComponentParameters(parameters?: Record<string, unknown>) {
		if (!parameters) return {};
		const normalized: Record<string, unknown> = { ...parameters };
		for (const [key, value] of Object.entries(parameters)) {
			const camelKey = key.includes('_')
				? key.replace(/_([a-z])/g, (_, c) => c.toUpperCase())
				: key;
			if (!(camelKey in normalized)) {
				normalized[camelKey] = value;
			}
		}
		return normalized;
	}

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
</script>

<div class="flex h-full flex-col">
	<!-- Breadcrumb -->
	<div class="mb-1">
		<nav class="text-xs" aria-label="Breadcrumb">
			<ol class="flex items-center gap-1">
				{#each breadcrumbs as crumb, i}
					<li class="flex items-center gap-1">
						{#if i > 0}
							<svg
								class="h-3 w-3 text-gray-400"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M9 5l7 7-7 7"
								></path>
							</svg>
						{/if}
						{#if crumb.current}
							<span class="font-medium text-gray-900 dark:text-gray-100">{crumb.label}</span>
						{:else}
							<a
								href={crumb.href}
								class="text-gray-500 hover:text-primary-600 dark:text-gray-400 dark:hover:text-primary-400 transition-colors"
							>
								{crumb.label}
							</a>
						{/if}
					</li>
				{/each}
			</ol>
		</nav>
		<div class="mt-1 flex items-baseline">
			<h1 class="text-2xl font-bold">{submodule?.name}</h1>
			{#if submodule?.description}
				<span class="mx-2 text-xl font-light text-gray-300 dark:text-gray-600">/</span>
				<p class="text-lg text-gray-500 font-normal dark:text-gray-400">{submodule.description}</p>
			{/if}
		</div>
	</div>

	<!-- Content Area -->
	<div
		class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 relative flex-1 overflow-hidden rounded-xl shadow-sm"
	>
		{#if program?.slug === 'crewbuilder'}
			<div class="absolute inset-0">
				<CrewBuilder moduleData={submodule} />
			</div>
		{:else if submodule?.type === 'component' && submodule?.path}
			<div class="absolute inset-0">
				{#if moduleComponent}
					{@const Component = moduleComponent}
					<Component {...moduleComponentProps} />
				{:else}
					<div
						class="flex h-full items-center justify-center text-center text-sm text-gray-500 dark:text-gray-400"
					>
						Unable to load component: {submodule.path}
					</div>
				{/if}
			</div>
		{:else}
			<!-- Module Placeholder -->
			<div class="flex h-full flex-col items-center justify-center text-center">
				<div
					class="bg-gray-100 dark:bg-gray-700 mb-6 flex h-24 w-24 items-center justify-center rounded-3xl"
				>
					<svg
						class="text-gray-400 dark:text-gray-500 h-12 w-12"
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
				<p class="text-gray-600 dark:text-gray-400 max-w-md">
					This is a <span class="badge">module</span> submodule. Custom Svelte components will be rendered
					here full-screen.
				</p>
				<div class="mt-6">
					<div class="badge badge-ghost">Component: Coming Soon</div>
				</div>
			</div>
		{/if}
	</div>
</div>
