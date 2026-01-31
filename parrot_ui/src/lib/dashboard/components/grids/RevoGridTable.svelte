<script lang="ts">
    import { RevoGrid } from "@revolist/svelte-datagrid";
    import type { TableWidget } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    // Derive RevoGrid configuration
    let columns = $derived(widget.getRevoGridColumns());
    let source = $derived(widget.tableData as Record<string, unknown>[]);

    let gridConfig = $derived({
        resize: widget.gridConfig.resizable,
        filter: widget.gridConfig.filterable,
    });
</script>

<div class="revogrid-wrapper">
    {#if columns.length > 0 && source.length > 0}
        <RevoGrid
            {columns}
            {source}
            resize={gridConfig.resize}
            filter={gridConfig.filter}
            theme="compact"
        />
    {:else if widget.loading}
        <div class="grid-loading">Loading...</div>
    {:else}
        <div class="grid-empty">No data available</div>
    {/if}
</div>

<style>
    .revogrid-wrapper {
        width: 100%;
        height: 100%;
        overflow: hidden;
    }

    .revogrid-wrapper :global(revo-grid) {
        width: 100%;
        height: 100%;
        min-height: 300px;
    }

    .grid-loading,
    .grid-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--text-secondary, #666);
        font-size: 0.9rem;
    }
</style>
