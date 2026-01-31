<script lang="ts">
    /**
     * Bridge Dashboard Component
     * 
     * This is a temporary bridge component that allows the AgentDashboard
     * to work with the new dashboard architecture. It adapts the local
     * DashboardModel pattern to the global dashboardContainer singleton.
     * 
     * TODO: Refactor AgentDashboard to use the new domain-driven architecture
     * or implement proper adapter pattern.
     */
    import type { DashboardModel } from '$lib/stores/dashboard/store.svelte';
    import DashboardContainer from '$lib/dashboard/components/dashboard/dashboard-container.svelte';
    
    interface Props {
        model?: DashboardModel;
    }
    
    let { model }: Props = $props();
    
    // For now, we just render the global container.
    // The AgentDashboard's local model isn't integrated yet.
    // This allows the build to pass while the feature is WIP.
</script>

<DashboardContainer />

<style>
    /* Bridge component - no additional styles needed */
</style>
