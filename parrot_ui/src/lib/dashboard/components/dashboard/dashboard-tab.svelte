<script lang="ts">
    import type { DashboardTab as DashboardTabClass } from "../../domain/dashboard-tab.svelte.js";
    import GridLayoutView from "../layouts/grid-layout.svelte";
    import FreeLayoutView from "../layouts/free-layout.svelte";
    import DockLayoutView from "../layouts/dock-layout.svelte";

    interface Props {
        tab: DashboardTabClass;
    }

    let { tab }: Props = $props();

    // Mapping layout mode to component
    let LayoutComponent = $derived.by(() => {
        switch (tab.layoutMode) {
            case "grid":
                return GridLayoutView;
            case "free":
                return FreeLayoutView;
            case "dock":
                return DockLayoutView;
            default:
                return GridLayoutView;
        }
    });

    // Type assertion for the layout prop
    let activeLayout = $derived(tab.layout as any);
</script>

<section class="dashboard-tab-view" data-id={tab.id}>
    <svelte:component this={LayoutComponent} layout={activeLayout} />
</section>

<style>
    .dashboard-tab-view {
        height: 100%;
        width: 100%;
        position: relative;
        overflow: hidden;
    }
</style>
