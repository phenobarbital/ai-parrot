<script lang="ts">
    import type { SimpleTableWidget } from "../../domain/simple-table-widget.svelte.js";

    interface Props {
        widget: SimpleTableWidget;
    }

    let { widget }: Props = $props();

    // Derived state
    let data = $derived(widget.tableData);
    let columns = $derived(widget.getEffectiveColumns());
    let zebra = $derived(widget.zebra);
    let totals = $derived(widget.totals);

    // Check if column should show total
    function shouldSum(col: (typeof columns)[0], rowData: unknown[]): boolean {
        if (col.summarize === true) return true;
        if (col.summarize === false) return false;
        // Heuristic: check if first row has numeric value
        if (rowData.length > 0) {
            const firstRow = rowData[0] as Record<string, unknown>;
            return typeof firstRow[col.key] === "number";
        }
        return false;
    }

    // Calculate column total
    function getColumnTotal(key: string): number {
        const values = data
            .map((row) => (row as Record<string, unknown>)[key])
            .filter((v): v is number => typeof v === "number");
        return widget.calculateTotal(values, totals);
    }
</script>

<div class="simple-table-container">
    {#if widget.loading}
        <div class="loading-state">
            <span class="spinner"></span>
            Loading data...
        </div>
    {:else if widget.error}
        <div class="error-state">
            <span class="icon">⚠️</span>
            <span>{widget.error}</span>
        </div>
    {:else if data.length === 0}
        <div class="empty-state">
            <span class="icon">📭</span>
            <span>No data available</span>
        </div>
    {:else}
        <table class="simple-table" class:zebra>
            <thead>
                <tr>
                    {#each columns as col}
                        {#if !col.hidden}
                            <th>{col.label ?? widget.humanize(col.key)}</th>
                        {/if}
                    {/each}
                </tr>
            </thead>
            <tbody>
                {#each data as row, i}
                    <tr>
                        {#each columns as col}
                            {#if !col.hidden}
                                {@const value = (
                                    row as Record<string, unknown>
                                )[col.key]}
                                {@const isNumeric =
                                    typeof value === "number" ||
                                    (col.mask && col.mask !== "string")}
                                <td class:text-right={isNumeric}>
                                    {widget.formatValue(value, col.mask)}
                                </td>
                            {/if}
                        {/each}
                    </tr>
                {/each}
            </tbody>
            {#if totals !== "none"}
                <tfoot>
                    <tr class="totals-row">
                        {#each columns as col, i}
                            {#if !col.hidden}
                                {#if shouldSum(col, data)}
                                    <td class="text-right">
                                        {widget.formatValue(
                                            getColumnTotal(col.key),
                                            col.mask,
                                        )}
                                    </td>
                                {:else if i === 0}
                                    <td class="total-label">
                                        Total ({totals})
                                    </td>
                                {:else}
                                    <td></td>
                                {/if}
                            {/if}
                        {/each}
                    </tr>
                </tfoot>
            {/if}
        </table>
    {/if}
</div>

<style>
    .simple-table-container {
        width: 100%;
        height: 100%;
        overflow: auto;
        padding: 8px;
        box-sizing: border-box;
    }

    .simple-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.875rem;
    }

    .simple-table th,
    .simple-table td {
        padding: 10px 12px;
        text-align: left;
        border-bottom: 1px solid var(--border, #e8eaed);
    }

    .simple-table th {
        background: var(--surface-2, #f8f9fa);
        font-weight: 600;
        color: var(--text, #202124);
        position: sticky;
        top: 0;
        z-index: 1;
    }

    .simple-table.zebra tbody tr:nth-child(even) {
        background: var(--surface-2, #f8f9fa);
    }

    .simple-table tbody tr:hover {
        background: var(--primary-light, #e8f0fe);
    }

    .text-right {
        text-align: right;
    }

    .totals-row {
        background: var(--surface-3, #f1f3f4);
        font-weight: 600;
    }

    .total-label {
        font-weight: 600;
        color: var(--text-2, #5f6368);
    }

    /* States */
    .loading-state,
    .error-state,
    .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        min-height: 150px;
        gap: 8px;
        color: var(--text-2, #5f6368);
    }

    .error-state {
        color: var(--danger, #dc3545);
    }

    .icon {
        font-size: 2rem;
    }

    .spinner {
        width: 24px;
        height: 24px;
        border: 3px solid var(--border, #e8eaed);
        border-top-color: var(--primary, #1a73e8);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>
