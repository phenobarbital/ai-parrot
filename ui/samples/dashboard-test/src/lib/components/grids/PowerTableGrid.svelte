<script lang="ts">
    import { PowerTable } from "@muonw/powertable";
    import type { TableWidget } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    // Derive PowerTable configuration
    let ptData = $derived(widget.tableData as Record<string, unknown>[]);
    let ptInstructs = $derived(
        widget.getEffectiveColumns().map((col) => ({
            key: col.key,
            title: col.label,
            sortable: widget.gridConfig.sortable,
        })),
    );
    let ptOptions = $derived({
        enableSearch: widget.gridConfig.filterable,
        enableRowNumbering: false,
        enablePagination: widget.gridConfig.pagination,
        rowsPerPage: widget.gridConfig.pageSize ?? 25,
    });
</script>

<div class="powertable-wrapper">
    {#if ptData.length > 0}
        <PowerTable {ptData} {ptInstructs} {ptOptions} />
    {:else if widget.loading}
        <div class="grid-loading">Loading...</div>
    {:else}
        <div class="grid-empty">No data available</div>
    {/if}
</div>

<style>
    .powertable-wrapper {
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

    /* Basic PowerTable styling */
    :global(.powertable-wrapper table) {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }

    :global(.powertable-wrapper th),
    :global(.powertable-wrapper td) {
        padding: 0.5rem 0.75rem;
        border: 1px solid var(--border-color, #e0e0e0);
        text-align: left;
    }

    :global(.powertable-wrapper th) {
        background: var(--header-bg, #f5f5f5);
        font-weight: 600;
    }

    :global(.powertable-wrapper tr:nth-child(even)) {
        background: var(--row-alt-bg, #fafafa);
    }

    :global(.powertable-wrapper tr:hover) {
        background: var(--row-hover-bg, #f0f0f0);
    }
</style>
