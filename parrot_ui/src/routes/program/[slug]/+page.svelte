<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import type { Program, Module } from '$lib/types';
	import { getModuleBySlug } from '$lib/data/manual-data';

	const program = $derived($page.data.program as Program);
	const modules = $derived(($page.data.modules as Module[]) || []);

	// Redirect to default module or first module's first submodule if available
	$effect(() => {
		if (modules.length > 0) {
			// 1. Check for Default Module
			if (program.defaultModuleslug) {
				const defaultModule = getModuleBySlug(program, program.defaultModuleslug);
				if (defaultModule && defaultModule.submodules.length > 0) {
					goto(`/program/${program.slug}/${defaultModule.slug}/${defaultModule.submodules[0].slug}`, {
						replaceState: true
					});
					return;
				}
			}

			// 2. Check for manual redirect logic if no default is set
			// (Only if we want to force open the first one - but requirements say "background if no module is selected by default")
			
			// Note: The user requirement says: "a property for define with is the default module, if not null, then we need to render that particular module"
			// It implies if it IS null, we should show the background. The previous code auto-redirected to the first module. 
			// I will REMOVE the auto-redirect to first module if defaultModuleslug is missing, to satisfy "a background (Watermark image) if no module is selected by default"
		}
	});
</script>

<div class="flex h-full flex-col items-center justify-center">
	<!-- Watermark / Background -->
	<div class="max-w-md text-center opacity-50">
		<div
			class="mx-auto mb-6 flex h-32 w-32 items-center justify-center rounded-full bg-base-300"
		>
			<img src={program?.icon?.startsWith('http') ? program.icon : '/favicon.png'} alt="Watermark" class="h-20 w-20 opacity-50 grayscale" />
		</div>
		<h1 class="mb-2 text-3xl font-bold text-base-content/40">{program?.name}</h1>
		<p class="text-base-content/40 mb-6">
			{program?.description || 'Select a module to get started.'}
		</p>
	</div>
</div>
