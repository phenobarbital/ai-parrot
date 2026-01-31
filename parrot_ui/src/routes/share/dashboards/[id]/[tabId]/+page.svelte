<script lang="ts">
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { resolveTab } from '$lib/share/resolver';
    import { hydrateMockData } from '$lib/data/mock-loader';
    import type { DashboardTab } from '$lib/dashboard/domain/dashboard-tab.svelte';
    import DashboardContainer from '$lib/dashboard/components/dashboard/dashboard-container.svelte';
    import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';

    let dashboardId = $derived($page.params.id);
    let tabId = $derived($page.params.tabId);
    
    let tab = $state<DashboardTab | undefined>(undefined);
    let loading = $state(true);
    let error = $state<string | null>(null);

    $effect(() => {
        loadTab(tabId);
    });

    async function loadTab(id: string) {
        loading = true;
        error = null;
        try {
            await hydrateMockData();
            // In our flattened model, checking the tab ID is sufficient
            const result = await resolveTab(id);
            if (result) {
                tab = result;
                dashboardContainer.activateTab(result.id);
            } else {
                error = 'Tab not found';
            }
        } catch (e) {
            error = 'Failed to load tab';
            console.error(e);
        } finally {
            loading = false;
        }
    }
</script>

<div class="h-screen w-full flex flex-col p-4">
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
    {:else if tab}
        <!-- Effectively the same as dashboard view for now since Dashboard component shows active tab -->
        <DashboardContainer />
    {/if}
</div>
