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

    let chartType = $state<ChartType>(widget.chartType);
    let xAxis = $state(widget.xAxis);
    let yAxis = $state(widget.yAxis);
    let labelColumn = $state(widget.labelColumn);
    let dataColumn = $state(widget.dataColumn);

    $effect(() => {
        onConfigChange({
            chartType,
            xAxis,
            yAxis,
            labelColumn,
            dataColumn,
        });
    });

    let isCartesian = $derived(
        ["line", "bar", "area", "stacked-area", "scatter"].includes(chartType),
    );
    let isPieDonut = $derived(["pie", "donut"].includes(chartType));
    let columns = $derived.by(() => {
        const data = widget.chartData as Record<string, unknown>[];
        if (!data || data.length === 0) return [];
        const first = data[0];
        if (typeof first !== "object" || first === null) return [];
        return Object.keys(first);
    });

    let hasColumns = $derived(columns.length > 0);
</script>

<div class="settings-tab">
    <div class="form-group">
        <label for="chart-type">Chart Type</label>
        <select id="chart-type" bind:value={chartType}>
            <option value="line">Line Chart</option>
            <option value="bar">Bar Chart</option>
            <option value="area">Area Chart</option>
            <option value="stacked-area">Stacked Area Chart</option>
            <option value="pie">Pie Chart</option>
            <option value="donut">Donut Chart</option>
            <option value="scatter">Scatter Plot</option>
        </select>
    </div>

    {#if isCartesian}
        <div class="form-row">
            <div class="form-group">
                <label for="x-axis">X Axis (Category)</label>
                {#if hasColumns}
                    <select id="x-axis" bind:value={xAxis}>
                        <option value="">-- Select Column --</option>
                        {#each columns as col}
                            <option value={col}>{col}</option>
                        {/each}
                    </select>
                {:else}
                    <input
                        id="x-axis"
                        type="text"
                        bind:value={xAxis}
                        placeholder="e.g. date"
                    />
                {/if}
                <p class="hint">Column for X Axis</p>
            </div>
            <div class="form-group">
                <label for="y-axis">Y Axis (Value)</label>
                {#if hasColumns}
                    <select id="y-axis" bind:value={yAxis}>
                        <option value="">-- Select Column --</option>
                        {#each columns as col}
                            <option value={col}>{col}</option>
                        {/each}
                    </select>
                {:else}
                    <input
                        id="y-axis"
                        type="text"
                        bind:value={yAxis}
                        placeholder="e.g. value"
                    />
                {/if}
                <p class="hint">Column for Y Axis</p>
            </div>
        </div>
    {/if}

    {#if isPieDonut}
        <div class="form-row">
            <div class="form-group">
                <label for="label-col">Label Column</label>
                {#if hasColumns}
                    <select id="label-col" bind:value={labelColumn}>
                        <option value="">-- Select Column --</option>
                        {#each columns as col}
                            <option value={col}>{col}</option>
                        {/each}
                    </select>
                {:else}
                    <input
                        id="label-col"
                        type="text"
                        bind:value={labelColumn}
                        placeholder="e.g. category"
                    />
                {/if}
            </div>
            <div class="form-group">
                <label for="data-col">Data Column</label>
                {#if hasColumns}
                    <select id="data-col" bind:value={dataColumn}>
                        <option value="">-- Select Column --</option>
                        {#each columns as col}
                            <option value={col}>{col}</option>
                        {/each}
                    </select>
                {:else}
                    <input
                        id="data-col"
                        type="text"
                        bind:value={dataColumn}
                        placeholder="e.g. value"
                    />
                {/if}
            </div>
        </div>
    {/if}
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
        flex: 1;
    }

    .form-row {
        display: flex;
        gap: 20px;
    }

    label {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    input,
    select {
        padding: 10px 12px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        background: var(--surface, #fff);
        width: 100%;
    }

    input:focus,
    select:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }

    .hint {
        margin: 0;
        font-size: 0.8rem;
        color: var(--text-3, #9aa0a6);
        font-style: italic;
    }
</style>
