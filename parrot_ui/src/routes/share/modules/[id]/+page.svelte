<script lang="ts">
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { resolveModule } from '$lib/share/resolver';
    import { hydrateMockData } from '$lib/data/mock-loader';
    import type { Module } from '$lib/types';
    import { goto } from '$app/navigation';

    let moduleId = $derived($page.params.id);
    let module = $state<Module | undefined>(undefined);
    let loading = $state(true);
    let error = $state<string | null>(null);

    $effect(() => {
        if (moduleId) {
            loadModule(moduleId);
        }
    });

    async function loadModule(id: string) {
        loading = true;
        error = null;
        try {
            await hydrateMockData(); // Ensure base data is loaded
            const result = await resolveModule(id);
            if (result) {
                module = result;
            } else {
                error = 'Module not found';
            }
        } catch (e) {
            error = 'Failed to load module';
            console.error(e);
        } finally {
            loading = false;
        }
    }

    // Handlers for submodule navigation within the shared view
    // Since we are in standalone mode, we might want to just render the first submodule
    // or provide a minimal tab switcher if there are multiple submodules.
    let activeSubmoduleSlug = $state<string | null>(null);

    $effect(() => {
        if (module && module.submodules.length > 0 && !activeSubmoduleSlug) {
            activeSubmoduleSlug = module.submodules[0].slug;
        }
    });

    const activeSubmodule = $derived(
        module?.submodules.find(s => s.slug === activeSubmoduleSlug)
    );

    // Registry of all potential module components
    const componentRegistry = import.meta.glob('$lib/components/**/*.svelte');

    // Mappings from mock-data struct to actual file paths if they differ slightly
    // Mock Data says: 'agents/AgentChat.svelte' (relative to lib/components?)
    // Real path: '$lib/components/agents/AgentChat.svelte'
    // Mock Data: 'modules/Demo/DemoDashboard.svelte'
    // Real path: '$lib/components/modules/Demo/DemoDashboard.svelte'

    // We can try to fuzzy match or constructing the known path prefixes
    function resolveComponent(pathProp: string) {
        // Try common prefixes
        const candidates = [
             `/src/lib/components/${pathProp}`,
             `/src/lib/${pathProp}`
        ];
        
        // Find matching key in registry
        for (const candidate of candidates) {
            // import.meta.glob keys are relative to root or absolute?
            // "The keys of the map are the relative paths from the current module... OR absolute if alias used?"
            // Actually usually relative to project root if starting with /
            
            // Let's normalize keys to be sure. componentRegistry keys usually look like:
            // "/src/lib/components/agents/AgentChat.svelte" (if using alias? no, usually relative to file or root)
            // Wait, import.meta.glob('$lib/...') might return keys with that alias or resolved.
            // Best practice: use relative glob from a known root like src/lib
        }
        return null;
    }
    
    // Better approach: explicit switch for known demo components to be 100% safe
    // But user wants "Dynamic" feel.
    // Let's use the registry with normalized checks.
    
    let CurrentComponent = $state<any>(null);
    let componentError = $state<string | null>(null);

    $effect(() => {
        if (!activeSubmodule || !activeSubmodule.path) {
             CurrentComponent = null;
             return;
        }
        
        loadComponent(activeSubmodule.path);
    });

    async function loadComponent(path: string) {
        CurrentComponent = null;
        componentError = null;

        // Construct standard path assuming structure in src/lib/components
        // Remove leading slash if any
        const cleanPath = path.replace(/^\//, '');
        const fullPath = `/src/lib/components/${cleanPath}`;

        // Registry keys are usually relative to the project root in Vite
        const loader = componentRegistry[fullPath];
        
        if (loader) {
            try {
                const module = await loader() as { default: any };
                CurrentComponent = module.default;
            } catch (e: any) {
                console.error('Failed to load component:', e);
                componentError = e.message;
            }
        } else {
             console.warn('Component not found in registry:', fullPath);
             console.log('Available keys:', Object.keys(componentRegistry));
             componentError = `Component not found: ${cleanPath}`;
        }
    }
</script>

<div class="h-screen w-full flex flex-col bg-base-100">
    {#if loading}
        <div class="flex flex-1 items-center justify-center">
            <span class="loading loading-spinner loading-lg text-primary"></span>
        </div>
    {:else if error}
        <div class="flex flex-1 items-center justify-center">
            <div class="alert alert-error max-w-md">
                <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                <span>{error}</span>
            </div>
        </div>
    {:else if module}
        <!-- Minimal Header for Module Context -->
        <div class="navbar bg-base-200 min-h-12 px-4 border-b border-base-300">
            <div class="flex-1 gap-2 items-center">
                <span class="font-bold text-lg">{module.name}</span>
            </div>
            <!-- Submodule Tabs if multiple -->
            {#if module.submodules.length > 1}
                <div class="flex-none">
                    <div role="tablist" class="tabs tabs-boxed tabs-sm">
                        {#each module.submodules as sub}
                            <button 
                                role="tab" 
                                class="tab {activeSubmoduleSlug === sub.slug ? 'tab-active' : ''}"
                                onclick={() => activeSubmoduleSlug = sub.slug}
                            >
                                {sub.name}
                            </button>
                        {/each}
                    </div>
                </div>
            {/if}
        </div>

        <!-- Content Area -->
        <div class="flex-1 overflow-hidden relative">
            {#if activeSubmodule}
                {#if activeSubmodule.type === 'component'}
                    {#if CurrentComponent}
                        <!-- Svelte 5 Dynamic Component -->
                        <CurrentComponent />
                    {:else if componentError}
                         <div class="p-4 flex flex-col items-center justify-center h-full text-error gap-2">
                            <h3 class="font-bold">Error Loading Implemenation</h3>
                            <p>{componentError}</p>
                            <p class="text-xs opacity-75">Path: {activeSubmodule.path}</p>
                        </div>
                    {:else}
                         <div class="flex flex-1 items-center justify-center h-full">
                            <span class="loading loading-spinner text-secondary"></span>
                        </div>
                    {/if}
                {:else}
                    <div class="flex items-center justify-center h-full text-base-content/50">
                        Submodule type '{activeSubmodule.type}' not fully supported in shared view yet.
                    </div>
                {/if}
            {/if}
        </div>
    {/if}
</div>
