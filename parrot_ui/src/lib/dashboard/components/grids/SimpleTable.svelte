<script lang="ts">
    import type { TableWidget } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
    }

    let { widget }: Props = $props();

    // Derive column and data configuration
    let columns = $derived(widget.columns);
    let data = $derived(widget.tableData as Record<string, unknown>[]);

    function formatValue(value: unknown): string {
        if (value === null || value === undefined) return "";
        if (typeof value === "object") return JSON.stringify(value);
        return String(value);
    }

    function humanize(key: string): string {
        return key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
    }
</script>

<div class="simple-table-wrapper">
    {#if data.length > 0}
        <table class="simple-table">
            <thead>
                <tr>
                    {#each columns as col}
                        <th>{col.headerName ?? humanize(col.field)}</th>
                    {/each}
                </tr>
            </thead>
            <tbody>
                {#each data as row, i}
                    <tr class:zebra={i % 2 === 1}>
                        {#each columns as col}
                            <td>{formatValue(row[col.field])}</td>
                        {/each}
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else if widget.loading}
        <div class="grid-loading">Loading...</div>
    {:else}
        <div class="grid-empty">No data available</div>
    {/if}
</div>

<style>
    .simple-table-wrapper {
        width: 100%;
        height: 100%;
        overflow: auto;
    }

    .simple-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }

    .simple-table th,
    .simple-table td {
        padding: 0.5rem 0.75rem;
        text-align: left;
        border-bottom: 1px solid var(--border-color, #e0e0e0);
    }

    .simple-table th {
        background: var(--header-bg, #f5f5f5);
        font-weight: 600;
        position: sticky;
        top: 0;
        z-index: 1;
    }

    .simple-table tbody tr:hover {
        background: var(--hover-bg, #f8f9fa);
    }

    .simple-table tbody tr.zebra {
        background: var(--zebra-bg, #fafafa);
    }

    .simple-table tbody tr.zebra:hover {
        background: var(--hover-bg, #f0f0f0);
    }

    .grid-loading,
    .grid-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        min-height: 200px;
        color: var(--text-secondary, #666);
        font-size: 0.9rem;
    }
</style>
