<script lang="ts">
    import type {
        GridConfig,
        GridType,
        TableWidget,
    } from "../../domain/table-widget.svelte.js";

    interface Props {
        widget: TableWidget;
        onConfigChange: (config: {
            gridType?: GridType;
            gridConfig?: Partial<GridConfig>;
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let gridType = $state<GridType>(widget.gridType);
    let pagination = $state(widget.gridConfig.pagination ?? false);
    let pageSize = $state(widget.gridConfig.pageSize?.toString() ?? "25");
    let sortable = $state(widget.gridConfig.sortable ?? true);
    let filterable = $state(widget.gridConfig.filterable ?? false);
    let resizable = $state(widget.gridConfig.resizable ?? true);

    $effect(() => {
        onConfigChange({
            gridType,
            gridConfig: {
                pagination,
                pageSize: pageSize ? Number(pageSize) : undefined,
                sortable,
                filterable,
                resizable,
            },
        });
    });
</script>

<div class="tab-section">
    <div class="form-group">
        <label for="grid-type">Grid Type</label>
        <select id="grid-type" bind:value={gridType}>
            <option value="gridjs">Grid.js</option>
            <option value="tabulator">Tabulator</option>
            <option value="revogrid">RevoGrid</option>
            <option value="powertable">PowerTable</option>
            <option value="flowbite">Flowbite</option>
            <option value="simple">Simple</option>
        </select>
    </div>

    <div class="form-group checkbox">
        <input id="pagination" type="checkbox" bind:checked={pagination} />
        <label for="pagination">Pagination</label>
    </div>

    <div class="form-group">
        <label for="page-size">Page Size</label>
        <input id="page-size" type="number" bind:value={pageSize} />
    </div>

    <div class="form-group checkbox">
        <input id="sortable" type="checkbox" bind:checked={sortable} />
        <label for="sortable">Sortable</label>
    </div>

    <div class="form-group checkbox">
        <input id="filterable" type="checkbox" bind:checked={filterable} />
        <label for="filterable">Filterable</label>
    </div>

    <div class="form-group checkbox">
        <input id="resizable" type="checkbox" bind:checked={resizable} />
        <label for="resizable">Resizable</label>
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
    select {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }
</style>
