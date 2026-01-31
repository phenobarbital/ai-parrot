<script lang="ts">
    import type { TableWidget } from "../../domain/table-widget.svelte.js";
    import GridJsTable from "../grids/GridJsTable.svelte";
    import TabulatorTable from "../grids/TabulatorTable.svelte";
    import RevoGridTable from "../grids/RevoGridTable.svelte";
    import PowerTableGrid from "../grids/PowerTableGrid.svelte";
    import FlowbiteTable from "../grids/FlowbiteTable.svelte";
    import SimpleTable from "../grids/SimpleTable.svelte";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    let gridType = $derived(widget.gridType);
</script>

<div class="table-widget-content">
    {#if widget.error}
        <div class="error-state">
            <span class="error-icon">⚠️</span>
            <span class="error-text">{widget.error}</span>
        </div>
    {:else if gridType === "gridjs"}
        <GridJsTable {widget} />
    {:else if gridType === "tabulator"}
        <TabulatorTable {widget} />
    {:else if gridType === "revogrid"}
        <RevoGridTable {widget} />
    {:else if gridType === "powertable"}
        <PowerTableGrid {widget} />
    {:else if gridType === "flowbite"}
        <FlowbiteTable {widget} />
    {:else}
        <SimpleTable {widget} />
    {/if}
</div>

<style>
    .table-widget-content {
        width: 100%;
        height: 100%;
        overflow: hidden;
        display: flex;
        flex-direction: column;
    }

    .error-state {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        height: 100%;
        padding: 1rem;
        background: var(--error-bg, #fff5f5);
        color: var(--error-color, #c53030);
        font-size: 0.9rem;
    }

    .error-icon {
        font-size: 1.25rem;
    }
</style>
