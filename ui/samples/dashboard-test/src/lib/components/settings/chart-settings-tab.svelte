<script lang="ts">
    import type {
        BaseChartWidget,
        ChartType,
    } from "../../domain/base-chart-widget.svelte.js";

    interface Props {
        widget: BaseChartWidget;
        onConfigChange: (config: {
            chartType?: ChartType;
            xAxis?: string;
            yAxis?: string;
            labelColumn?: string;
            dataColumn?: string;
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    const chartTypes: Array<{ value: ChartType; label: string }> = [
        { value: "bar", label: "Bar" },
        { value: "line", label: "Line" },
        { value: "area", label: "Area" },
        { value: "stacked-area", label: "Stacked Area" },
        { value: "pie", label: "Pie" },
        { value: "donut", label: "Donut" },
        { value: "scatter", label: "Scatter" },
    ];

    let chartType = $state<ChartType>(widget.chartType);
    let xAxis = $state(widget.xAxis ?? "");
    let yAxis = $state(widget.yAxis ?? "");
    let labelColumn = $state(widget.labelColumn ?? "");
    let dataColumn = $state(widget.dataColumn ?? "");

    let availableColumns = $derived.by(() => {
        const data = widget.chartData;
        if (!data.length) return [] as string[];
        const sample = data.find((row) => typeof row === "object" && row !== null);
        if (!sample || Array.isArray(sample)) return [] as string[];
        return Object.keys(sample as Record<string, unknown>);
    });

    let isPieChart = $derived.by(() => ["pie", "donut"].includes(chartType));

    $effect(() => {
        onConfigChange({
            chartType,
            xAxis,
            yAxis,
            labelColumn,
            dataColumn,
        });
    });
</script>

<div class="chart-settings">
    <div class="form-group">
        <label for="chart-type">Chart Type</label>
        <select id="chart-type" bind:value={chartType}>
            {#each chartTypes as type}
                <option value={type.value}>{type.label}</option>
            {/each}
        </select>
    </div>

    {#if isPieChart}
        <div class="form-row">
            <div class="form-group">
                <label for="label-column">Label Column</label>
                <input
                    id="label-column"
                    type="text"
                    list="chart-column-options"
                    bind:value={labelColumn}
                    placeholder="e.g. category"
                />
            </div>
            <div class="form-group">
                <label for="data-column">Value Column</label>
                <input
                    id="data-column"
                    type="text"
                    list="chart-column-options"
                    bind:value={dataColumn}
                    placeholder="e.g. amount"
                />
            </div>
        </div>
    {:else}
        <div class="form-row">
            <div class="form-group">
                <label for="x-axis">X Axis</label>
                <input
                    id="x-axis"
                    type="text"
                    list="chart-column-options"
                    bind:value={xAxis}
                    placeholder="e.g. date"
                />
            </div>
            <div class="form-group">
                <label for="y-axis">Y Axis</label>
                <input
                    id="y-axis"
                    type="text"
                    list="chart-column-options"
                    bind:value={yAxis}
                    placeholder="e.g. total"
                />
            </div>
        </div>
    {/if}

    {#if availableColumns.length}
        <p class="helper-text">
            Available columns: {availableColumns.join(", ")}
        </p>
    {:else}
        <p class="helper-text helper-muted">
            Load data first to see column suggestions.
        </p>
    {/if}

    <datalist id="chart-column-options">
        {#each availableColumns as column}
            <option value={column}></option>
        {/each}
    </datalist>
</div>

<style>
    .chart-settings {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .form-row {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .form-group label {
        font-size: 0.85rem;
        font-weight: 600;
    }

    .form-group input,
    .form-group select {
        padding: 8px 10px;
        border-radius: 6px;
        border: 1px solid var(--border, #444);
        background: var(--surface-2, #1f1f1f);
        color: inherit;
    }

    .helper-text {
        margin: 0;
        font-size: 0.8rem;
        color: var(--text-2, #9aa0a6);
    }

    .helper-muted {
        opacity: 0.8;
    }
</style>
