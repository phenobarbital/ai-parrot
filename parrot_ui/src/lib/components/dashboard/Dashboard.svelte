<script lang="ts">
    /**
     * Wrapper component that re-exports the dashboard container from the new location.
     * This bridges the old import path used by AgentDashboard.svelte
     */
    import DashboardContainerView from "$lib/dashboard/components/dashboard/dashboard-container.svelte";
</script>

<DashboardContainerView />
