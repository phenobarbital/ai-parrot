<script lang="ts">
    import type {
        TableWidget,
        GridType,
        GridConfig,
    } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
        onConfigChange: (config: {
            gridType?: GridType;
            gridConfig?: Partial<GridConfig>;
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    // Local state initialized from widget
    let gridType = $state<GridType>(widget.gridType);
    let pagination = $state(widget.gridConfig.pagination ?? false);
    let pageSize = $state(widget.gridConfig.pageSize ?? 25);
    let sortable = $state(widget.gridConfig.sortable ?? true);
    let filterable = $state(widget.gridConfig.filterable ?? false);
    let resizable = $state(widget.gridConfig.resizable ?? true);

    const gridTypes: { value: GridType; label: string; description: string }[] =
        [
            {
                value: "gridjs",
                label: "Grid.js",
                description: "Lightweight, easy to use",
            },
            {
                value: "tabulator",
                label: "Tabulator",
                description: "Interactive, fully featured",
            },
            {
                value: "revogrid",
                label: "RevoGrid",
                description: "Excel-like, virtual scrolling",
            },
            {
                value: "powertable",
                label: "PowerTable",
                description: "Sorting, filtering, inline editing",
            },
            {
                value: "flowbite",
                label: "Flowbite",
                description: "Tailwind-styled table",
            },
            {
                value: "simple",
                label: "Simple Table",
                description: "Native HTML table",
            },
        ];

    // Notify parent on any change
    function notifyChange() {
        onConfigChange({
            gridType,
            gridConfig: {
                pagination,
                pageSize,
                sortable,
                filterable,
                resizable,
            },
        });
    }

    // Call notifyChange whenever state changes
    $effect(() => {
        notifyChange();
    });
</script>

<div class="table-settings-tab">
    <!-- Grid Type Selector -->
    <section class="settings-section">
        <h3 class="section-title">Grid Type</h3>
        <div class="grid-type-selector">
            {#each gridTypes as gt}
                <label
                    class="grid-type-option"
                    class:selected={gridType === gt.value}
                >
                    <input
                        type="radio"
                        name="grid-type"
                        value={gt.value}
                        bind:group={gridType}
                    />
                    <div class="option-content">
                        <span class="option-label">{gt.label}</span>
                        <span class="option-desc">{gt.description}</span>
                    </div>
                </label>
            {/each}
        </div>
    </section>

    <!-- Grid Configuration -->
    <section class="settings-section">
        <h3 class="section-title">Grid Options</h3>

        <div class="checkbox-group">
            <label class="checkbox-option">
                <input type="checkbox" bind:checked={pagination} />
                <span>Enable pagination</span>
            </label>
        </div>

        {#if pagination}
            <div class="form-group inline">
                <label for="page-size">Page size</label>
                <select id="page-size" bind:value={pageSize}>
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                </select>
            </div>
        {/if}

        <div class="checkbox-group">
            <label class="checkbox-option">
                <input type="checkbox" bind:checked={sortable} />
                <span>Enable sorting</span>
            </label>
            <label class="checkbox-option">
                <input type="checkbox" bind:checked={filterable} />
                <span>Enable filtering</span>
            </label>
            <label class="checkbox-option">
                <input type="checkbox" bind:checked={resizable} />
                <span>Resizable columns</span>
            </label>
        </div>
    </section>

    <!-- Grid-specific settings placeholder -->
    <section class="settings-section">
        <h3 class="section-title">Advanced</h3>
        <p class="hint">
            Grid-specific configuration options will be available here based on
            the selected grid type.
        </p>
    </section>
</div>

<style>
    .table-settings-tab {
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 1.5rem;
    }

    .settings-section {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .section-title {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--text-primary, #333);
        margin: 0;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--border-color, #e0e0e0);
    }

    .grid-type-selector {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 0.5rem;
    }

    .grid-type-option {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.75rem;
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        cursor: pointer;
        transition: all 0.15s ease;
    }

    .grid-type-option:hover {
        border-color: var(--primary-color, #4a90d9);
        background: var(--hover-bg, #f8f9fa);
    }

    .grid-type-option.selected {
        border-color: var(--primary-color, #4a90d9);
        background: var(--selected-bg, #e8f0fe);
    }

    .grid-type-option input[type="radio"] {
        margin-top: 0.15rem;
    }

    .option-content {
        display: flex;
        flex-direction: column;
        gap: 0.125rem;
    }

    .option-label {
        font-weight: 500;
        font-size: 0.85rem;
    }

    .option-desc {
        font-size: 0.75rem;
        color: var(--text-secondary, #666);
    }

    .checkbox-group {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .checkbox-option {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.85rem;
        cursor: pointer;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .form-group.inline {
        flex-direction: row;
        align-items: center;
        gap: 0.75rem;
    }

    .form-group label {
        font-size: 0.8rem;
        color: var(--text-secondary, #666);
    }

    .form-group select {
        padding: 0.375rem 0.5rem;
        border: 1px solid var(--border-color, #ccc);
        border-radius: 4px;
        font-size: 0.85rem;
    }

    .hint {
        font-size: 0.8rem;
        color: var(--text-secondary, #666);
        font-style: italic;
        margin: 0;
    }
</style>
