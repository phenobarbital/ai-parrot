<script lang="ts">
    import { onMount } from "svelte";
    import { TabulatorFull as Tabulator } from "tabulator-tables";
    import "tabulator-tables/dist/css/tabulator.min.css";
    import type { TableWidget } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    let tableContainer: HTMLDivElement;
    let table: Tabulator | null = null;

    // Derive configuration
    let columns = $derived(
        widget.getEffectiveColumns().map((col) => ({
            title: col.label ?? col.key,
            field: col.key,
            sorter: "string" as const,
            headerFilter: widget.gridConfig.filterable
                ? ("input" as const)
                : undefined,
        })),
    );
    let data = $derived(widget.tableData as Record<string, unknown>[]);

    onMount(() => {
        if (tableContainer && data.length > 0) {
            table = new Tabulator(tableContainer, {
                data,
                columns,
                layout: "fitColumns",
                pagination: widget.gridConfig.pagination,
                paginationSize: widget.gridConfig.pageSize ?? 25,
                movableColumns: true,
                resizableColumns: widget.gridConfig.resizable,
            });
        }

        return () => {
            if (table) {
                table.destroy();
                table = null;
            }
        };
    });

    // Update data when it changes
    $effect(() => {
        if (table && data.length > 0) {
            table.setData(data);
        }
    });
</script>

<div class="tabulator-wrapper">
    {#if data.length > 0}
        <div bind:this={tableContainer} class="tabulator-container"></div>
    {:else if widget.loading}
        <div class="grid-loading">Loading...</div>
    {:else}
        <div class="grid-empty">No data available</div>
    {/if}
</div>

<style>
    .tabulator-wrapper {
        width: 100%;
        height: 100%;
        overflow: auto;
    }

    .tabulator-container {
        width: 100%;
        height: 100%;
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
