<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import type { Program, Module } from '$lib/types';
	import { getModuleBySlug } from '$lib/data/mock-data';

	const program = $derived($page.data.program as Program);
	const moduleSlug = $derived($page.params.module);

	const module = $derived.by(() => {
		if (program && moduleSlug) {
			return getModuleBySlug(program, moduleSlug);
		}
		return null;
	});

	// Redirect to first submodule if available
	$effect(() => {
		if (module && module.submodules.length > 0) {
			const firstSubmodule = module.submodules[0];
			goto(`/program/${program.slug}/${module.slug}/${firstSubmodule.slug}`, {
				replaceState: true
			});
		}
	});
</script>

<div class="flex h-full flex-col items-center justify-center">
	<div class="max-w-md text-center">
		<div class="bg-base-300 mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl">
			<svg class="text-base-content/50 h-10 w-10" fill="currentColor" viewBox="0 0 24 24">
				<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"></path>
			</svg>
		</div>
		<h1 class="mb-2 text-2xl font-bold">{module?.name || 'Module'}</h1>
		<p class="text-base-content/60 mb-6">
			{module?.description || 'Select a submodule from the sidebar.'}
		</p>

		{#if module && module.submodules.length === 0}
			<div class="alert alert-info">
				<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
					></path>
				</svg>
				<span>No submodules available for this module.</span>
			</div>
		{/if}
	</div>
</div>
