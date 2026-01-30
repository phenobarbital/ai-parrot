<script lang="ts">
    import {
        Table,
        TableBody,
        TableBodyCell,
        TableBodyRow,
        TableHead,
        TableHeadCell,
    } from "flowbite-svelte";
    import type { TableWidget } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    // Derive configuration
    let columns = $derived(widget.getEffectiveColumns());
    let data = $derived(widget.tableData as Record<string, unknown>[]);

    // Format cell value for display
    function formatValue(value: unknown): string {
        if (value === null || value === undefined) return "";
        if (typeof value === "object") return JSON.stringify(value);
        return String(value);
    }
</script>

<div class="flowbite-wrapper">
    {#if columns.length > 0 && data.length > 0}
        <Table striped={true} hoverable={true}>
            <TableHead>
                {#each columns as col (col.key)}
                    <TableHeadCell>{col.label}</TableHeadCell>
                {/each}
            </TableHead>
            <TableBody>
                {#each data as row, idx (idx)}
                    <TableBodyRow>
                        {#each columns as col (col.key)}
                            <TableBodyCell>
                                {formatValue(row[col.key])}
                            </TableBodyCell>
                        {/each}
                    </TableBodyRow>
                {/each}
            </TableBody>
        </Table>
    {:else if widget.loading}
        <div class="grid-loading">Loading...</div>
    {:else}
        <div class="grid-empty">No data available</div>
    {/if}
</div>

<style>
    .flowbite-wrapper {
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
</style>
