<script lang="ts">
    import Grid from "gridjs-svelte";
    import "gridjs/dist/theme/mermaid.css";
    import type { TableWidget } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    // Derive Grid.js configuration
    let columns = $derived(widget.getGridJsColumns());
    let data = $derived(
        widget.tableData.map((row) => {
            const r = row as Record<string, unknown>;
            return columns.map((col) => {
                const value = r[col.id];
                if (value === null || value === undefined) return "";
                if (typeof value === "object") return JSON.stringify(value);
                return value;
            });
        }),
    );

    let gridConfig = $derived({
        pagination: widget.gridConfig.pagination
            ? { limit: widget.gridConfig.pageSize ?? 25 }
            : false,
        sort: widget.gridConfig.sortable,
        resizable: widget.gridConfig.resizable,
    });
</script>

<div class="gridjs-wrapper">
    {#if columns.length > 0 && data.length > 0}
        <Grid
            columns={columns.map((c) => c.name)}
            {data}
            pagination={gridConfig.pagination}
            sort={gridConfig.sort}
            resizable={gridConfig.resizable}
        />
    {:else if widget.loading}
        <div class="grid-loading">Loading...</div>
    {:else}
        <div class="grid-empty">No data available</div>
    {/if}
</div>

<style>
    .gridjs-wrapper {
        width: 100%;
        height: 100%;
        overflow: auto;
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

    :global(.gridjs-wrapper .gridjs-container) {
        font-size: 0.85rem;
    }

    :global(.gridjs-wrapper .gridjs-table) {
        width: 100%;
    }
</style>
