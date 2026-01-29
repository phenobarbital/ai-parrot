<script lang="ts">
    import type { ChartType } from "../../domain/base-chart-widget.svelte.js";

    interface Props {
        widget: {
            chartType: ChartType;
            xAxis: string;
            yAxis: string;
            labelColumn: string;
            dataColumn: string;
        };
        onConfigChange: (config: {
            chartType?: ChartType;
            xAxis?: string;
            yAxis?: string;
            labelColumn?: string;
            dataColumn?: string;
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let chartType = $state<ChartType>(widget.chartType ?? "bar");
    let xAxis = $state(widget.xAxis ?? "");
    let yAxis = $state(widget.yAxis ?? "");
    let labelColumn = $state(widget.labelColumn ?? "");
    let dataColumn = $state(widget.dataColumn ?? "");

    $effect(() => {
        onConfigChange({ chartType, xAxis, yAxis, labelColumn, dataColumn });
    });
</script>

<div class="tab-section">
    <div class="form-group">
        <label for="chart-type">Chart Type</label>
        <select id="chart-type" bind:value={chartType}>
            <option value="bar">Bar</option>
            <option value="line">Line</option>
            <option value="area">Area</option>
            <option value="stacked-area">Stacked Area</option>
            <option value="pie">Pie</option>
            <option value="donut">Donut</option>
            <option value="scatter">Scatter</option>
        </select>
    </div>

    <div class="form-group">
        <label for="x-axis">X Axis</label>
        <input id="x-axis" type="text" bind:value={xAxis} />
    </div>

    <div class="form-group">
        <label for="y-axis">Y Axis</label>
        <input id="y-axis" type="text" bind:value={yAxis} />
    </div>

    <div class="form-group">
        <label for="label-column">Label Column (Pie/Donut)</label>
        <input id="label-column" type="text" bind:value={labelColumn} />
    </div>

    <div class="form-group">
        <label for="data-column">Data Column (Pie/Donut)</label>
        <input id="data-column" type="text" bind:value={dataColumn} />
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

    input,
    select {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }
</style>
