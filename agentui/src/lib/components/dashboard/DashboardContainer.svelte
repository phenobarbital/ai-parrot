<script lang="ts">
    import { type DashboardContainerStore } from '$lib/stores/dashboard/store.svelte';
    import Dashboard from './Dashboard.svelte';

    let { store } = $props<{ store: DashboardContainerStore }>();

    let activeDashboard = $derived(store.activeDashboard);

    function handleAdd() {
        store.addDashboard();
    }

    function handleSwitch(id: string) {
        store.activate(id);
    }

    function handleClose(id: string, e: Event) {
        e.stopPropagation();
        store.removeDashboard(id);
    }
</script>

<div class="dashboard-container w-full h-full flex flex-col bg-base-100">
    <!-- Tab Bar -->
    <div class="h-10 border-b border-base-300 flex items-end px-2 gap-1 bg-base-200/50">
        <!-- Tabs -->
        <div class="flex-1 flex overflow-x-auto no-scrollbar gap-1">
            {#each store.dashboards as dash (dash.id)}
                <button 
                    class="
                        group relative flex items-center gap-2 px-3 py-1.5 rounded-t-lg text-sm transition-colors border-t border-x border-transparent
                        {activeDashboard?.id === dash.id 
                            ? 'bg-base-100 border-base-300 text-base-content font-medium -mb-px pb-2 z-10' 
                            : 'hover:bg-base-200 text-base-content/70 hover:text-base-content'
                        }
                    "
                    onclick={() => handleSwitch(dash.id)}
                >
                    <span class="opacity-70">{dash.icon}</span>
                    <span class="truncate max-w-[120px]">{dash.title}</span>
                    
                    <!-- Tab Close -->
                    <div 
                        class="ml-1 w-4 h-4 rounded-full flex items-center justify-center hover:bg-base-300 opacity-0 group-hover:opacity-100 transition-opacity"
                        role="button"
                        tabindex="0"
                        onclick={(e) => handleClose(dash.id, e)}
                        onkeydown={(e) => e.key === 'Enter' && handleClose(dash.id, e)}
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
                            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                        </svg>
                    </div>
                </button>
            {/each}
        </div>

        <!-- Add Button -->
        <button 
            class="btn btn-ghost btn-sm btn-square mb-1" 
            title="New Dashboard"
            onclick={handleAdd}
        >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
              <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
            </svg>
        </button>
    </div>

    <!-- Content -->
    <div class="flex-1 min-h-0 bg-base-200/30 overflow-hidden relative">
        {#if activeDashboard}
            <!-- Pass the MODEL to Dashboard, NOT the global store -->
            <Dashboard model={activeDashboard} />
        {:else}
            <div class="flex flex-col items-center justify-center h-full opacity-30 gap-4">
                <div class="text-6xl">📊</div>
                <div class="text-xl font-medium">No active dashboard</div>
                <button class="btn btn-primary" onclick={handleAdd}>Create Dashboard</button>
            </div>
        {/if}
    </div>
</div>
