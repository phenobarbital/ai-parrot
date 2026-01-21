<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import type { Program, Module } from '$lib/types';

	import { toolbarStore } from '$lib/stores/toolbar.svelte';

	const program = $derived($page.data.program as Program);
	const modules = $derived(($page.data.modules as Module[]) || []);

	$effect(() => {
		// Test button removed
	});

	// Redirect to first module's first submodule if available
	$effect(() => {
		if (modules.length > 0 && modules[0].submodules.length > 0) {
			const firstModule = modules[0];
			const firstSubmodule = firstModule.submodules[0];
			goto(`/program/${program.slug}/${firstModule.slug}/${firstSubmodule.slug}`, {
				replaceState: true
			});
		}
	});
</script>

<div class="flex h-full flex-col items-center justify-center">
	<div class="max-w-md text-center">
		<div
			class="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl"
			style="background: linear-gradient(135deg, {program?.color || '#6366F1'}, {program?.color ||
				'#6366F1'}88)"
		>
			<svg class="h-12 w-12 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
				></path>
			</svg>
		</div>
		<h1 class="mb-2 text-2xl font-bold">{program?.name}</h1>
		<p class="text-base-content/60 mb-6">
			{program?.description || 'Select a module from the sidebar to get started.'}
		</p>

		{#if modules.length === 0}
			<div class="alert alert-info">
				<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
					></path>
				</svg>
				<span>No modules available for this program.</span>
			</div>
		{/if}
	</div>
</div>
