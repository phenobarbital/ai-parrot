<script lang="ts">
    import type {
        ColumnConfig,
        SimpleTableWidget,
        TotalType,
    } from "../../domain/simple-table-widget.svelte.js";

    interface Props {
        widget: SimpleTableWidget;
        onConfigChange: (config: {
            zebra?: boolean;
            totals?: TotalType;
            columns?: ColumnConfig[];
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let zebra = $state(widget.zebra);
    let totals = $state<TotalType>(widget.totals);
    let columnsText = $state(
        widget.columns.length ? JSON.stringify(widget.columns, null, 2) : "",
    );

    function parseColumns(text: string): ColumnConfig[] | undefined {
        if (!text.trim()) return undefined;
        try {
            const parsed = JSON.parse(text);
            return Array.isArray(parsed) ? parsed : undefined;
        } catch {
            return undefined;
        }
    }

    $effect(() => {
        const parsedColumns = parseColumns(columnsText);
        onConfigChange({
            zebra,
            totals,
            ...(parsedColumns ? { columns: parsedColumns } : {}),
        });
    });
</script>

<div class="tab-section">
    <div class="form-group checkbox">
        <input id="zebra" type="checkbox" bind:checked={zebra} />
        <label for="zebra">Zebra striping</label>
    </div>

    <div class="form-group">
        <label for="totals">Totals</label>
        <select id="totals" bind:value={totals}>
            <option value="none">None</option>
            <option value="sum">Sum</option>
            <option value="avg">Average</option>
            <option value="median">Median</option>
        </select>
    </div>

    <div class="form-group">
        <label for="columns">Columns (JSON)</label>
        <textarea id="columns" rows="6" bind:value={columnsText}></textarea>
    </div>
</div>

<style>
    .tab-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .form-group label {
        display: block;
        margin-bottom: 6px;
        font-size: 0.875rem;
        font-weight: 500;
    }

    .checkbox {
        display: flex;
        gap: 8px;
        align-items: center;
    }

    input[type="checkbox"] {
        width: 18px;
        height: 18px;
    }

    input,
    select,
    textarea {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }

    textarea {
        font-family: monospace;
    }
</style>
