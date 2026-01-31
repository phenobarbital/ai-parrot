<script lang="ts">
    import type {
        SimpleTableWidget,
        TotalType,
        ColumnConfig,
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

    // Initialize from widget
    let zebra = $state(widget.zebra);
    let totals = $state<TotalType>(widget.totals);
    let columnsJson = $state(JSON.stringify(widget.columns, null, 2));

    // Validation
    let columnsError = $state("");

    function validateColumnsJson(json: string): ColumnConfig[] | null {
        try {
            const parsed = JSON.parse(json);
            if (!Array.isArray(parsed)) return null;
            return parsed as ColumnConfig[];
        } catch {
            return null;
        }
    }

    // Notify parent on changes
    $effect(() => {
        const cols = validateColumnsJson(columnsJson);
        if (columnsJson.trim() !== "" && cols === null) {
            columnsError = "Invalid JSON array";
            return;
        }
        columnsError = "";

        onConfigChange({
            zebra,
            totals,
            columns: cols ?? [],
        });
    });
</script>

<div class="settings-tab">
    <!-- Zebra Striping -->
    <div class="form-group checkbox-row">
        <input id="zebra-check" type="checkbox" bind:checked={zebra} />
        <label for="zebra-check">Enable zebra striping</label>
    </div>

    <!-- Totals Row -->
    <div class="form-group">
        <label for="totals-select">Totals Row</label>
        <select id="totals-select" bind:value={totals}>
            <option value="none">None</option>
            <option value="sum">Sum</option>
            <option value="avg">Average</option>
            <option value="median">Median</option>
        </select>
        <p class="hint">Calculate totals for numeric columns.</p>
    </div>

    <!-- Columns Configuration -->
    <div class="form-group">
        <label for="columns-json">Columns Configuration (JSON)</label>
        <textarea
            id="columns-json"
            bind:value={columnsJson}
            class:has-error={!!columnsError}
            rows="8"
            placeholder={`[
  { "key": "name", "label": "Name" },
  { "key": "amount", "mask": "money", "summarize": true }
]`}
        ></textarea>
        {#if columnsError}
            <span class="error-msg">{columnsError}</span>
        {:else}
            <p class="hint">Leave empty to auto-detect from data.</p>
        {/if}
    </div>

    <!-- Column Config Reference -->
    <details class="help-section">
        <summary>Column Config Reference</summary>
        <div class="help-content">
            <ul>
                <li><code>key</code>: Field name in data (required)</li>
                <li><code>label</code>: Column header text</li>
                <li>
                    <code>mask</code>: <code>money</code>, <code>percent</code>,
                    <code>number</code>, or <code>string</code>
                </li>
                <li><code>hidden</code>: Hide column (boolean)</li>
                <li><code>summarize</code>: Include in totals (boolean)</li>
            </ul>
        </div>
    </details>
</div>

<style>
    .settings-tab {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .checkbox-row {
        flex-direction: row;
        align-items: center;
        gap: 8px;
    }

    .checkbox-row input {
        width: 18px;
        height: 18px;
    }

    .checkbox-row label {
        margin: 0;
        font-weight: 400;
    }

    label {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    select,
    textarea {
        padding: 10px 12px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        background: var(--surface, #fff);
        font-family: inherit;
    }

    textarea {
        font-family: monospace;
        font-size: 0.9rem;
        resize: vertical;
    }

    select:focus,
    textarea:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }

    .has-error {
        border-color: var(--danger, #dc3545);
    }

    .error-msg {
        font-size: 0.8rem;
        color: var(--danger, #dc3545);
    }

    .hint {
        margin: 0;
        font-size: 0.8rem;
        color: var(--text-3, #9aa0a6);
        font-style: italic;
    }

    .help-section {
        border: 1px solid var(--border, #e8eaed);
        border-radius: 6px;
        background: var(--surface-2, #f8f9fa);
    }

    .help-section summary {
        padding: 10px 12px;
        cursor: pointer;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--text-2, #5f6368);
    }

    .help-content {
        padding: 0 12px 12px;
        font-size: 0.8rem;
        color: var(--text-2, #5f6368);
    }

    .help-content ul {
        margin: 0;
        padding-left: 20px;
    }

    .help-content li {
        margin-bottom: 4px;
    }

    .help-content code {
        background: rgba(0, 0, 0, 0.05);
        padding: 1px 4px;
        border-radius: 3px;
        font-family: monospace;
    }
</style>
