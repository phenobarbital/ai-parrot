<script lang="ts">
    import { page } from '$app/stores';
    import { onMount, type Component } from 'svelte';
    import { resolveWidget } from '$lib/share/resolver';
    import { hydrateMockData } from '$lib/data/mock-loader';
    import type { Widget } from '$lib/dashboard/domain/widget.svelte.js';

    let widgetId = $derived($page.params.id);
    let widget = $state<Widget | undefined>(undefined);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let WidgetComponent = $state<Component<any> | null>(null);

    // Load widget data
    $effect(() => {
        loadWidget(widgetId);
    });

    // Dynamically load the renderer to avoid SSR issues with Leaflet/Charts
    $effect(() => {
        loadRenderer();
    });

    async function loadRenderer() {
        try {
            const module = await import('$lib/dashboard/components/widgets/widget-renderer.svelte');
            WidgetComponent = module.default;
        } catch (e) {
            console.error("Failed to load widget renderer:", e);
        }
    }

    async function loadWidget(id: string) {
        loading = true;
        error = null;
        try {
            // await hydrateMockData(); // Clean share view relies on snapshots
            const result = await resolveWidget(id);
            if (result) {
                widget = result;
            } else {
                error = 'Widget not found';
            }
        } catch (e) {
            error = 'Failed to load widget';
            console.error(e);
        } finally {
            loading = false;
        }
    }
</script>

<div class="h-screen w-full flex flex-col p-4 bg-base-200/50">
    {#if loading || !WidgetComponent}
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
    {:else if widget}
        <div class="flex-1 relative">
            <WidgetComponent {widget} />
        </div>
    {/if}
</div>
