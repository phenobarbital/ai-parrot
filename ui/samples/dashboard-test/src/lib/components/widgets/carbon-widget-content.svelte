<script lang="ts">
    import "@carbon/charts-svelte/styles.css";
    import type { CarbonChartsWidget } from "../../domain/carbon-charts-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";
    import { onMount } from "svelte";

    let { widget } = $props<{ widget: CarbonChartsWidget }>();

    // Dynamically loaded chart components
    let BarChartSimple: any = $state(null);
    let LineChart: any = $state(null);
    let AreaChart: any = $state(null);
    let PieChart: any = $state(null);
    let DonutChart: any = $state(null);
    let ScatterChart: any = $state(null);
    let StackedAreaChart: any = $state(null);

    let error = $state("");
    let loaded = $state(false);

    onMount(async () => {
        try {
            const charts = await import("@carbon/charts-svelte");
            BarChartSimple = charts.BarChartSimple;
            LineChart = charts.LineChart;
            AreaChart = charts.AreaChart;
            PieChart = charts.PieChart;
            DonutChart = charts.DonutChart;
            ScatterChart = charts.ScatterChart;
            StackedAreaChart = charts.StackedAreaChart;
            loaded = true;
        } catch (e) {
            console.error("Failed to load @carbon/charts-svelte", e);
            error = "Failed to load Carbon Charts library";
        }
    });

    // Transform widget data for Carbon Charts format
    let chartData = $derived.by(() => {
        const xCol = widget.xAxis;
        const yCol = widget.yAxis;
        const type = widget.chartType;

        if (!widget.chartData.length) return [];

        // For pie/donut charts, use labelColumn and dataColumn
        if (["pie", "donut"].includes(type)) {
            const labelCol =
                widget.labelColumn ||
                xCol ||
                Object.keys(widget.chartData[0] as object)[0];
            const dataCol =
                widget.dataColumn ||
                yCol ||
                Object.keys(widget.chartData[0] as object)[1];
            return widget.chartData.map((d: any) => ({
                group: String(d[labelCol]),
                value: Number(d[dataCol]) || 0,
            }));
        }

        // For bar/line/area/scatter, map to group/value format
        const keys = Object.keys(widget.chartData[0] as object);
        const xField = xCol || keys[0];
        const yField = yCol || keys[1] || keys[0];

        return widget.chartData.map((d: any) => ({
            group: String(d[xField]),
            value: Number(d[yField]) || 0,
        }));
    });

    // Carbon Charts options
    let options = $derived({
        theme: "g90", // Dark theme that works well
        height: "100%",
        resizable: true,
        axes: {
            left: { mapsTo: "value" },
            bottom: { mapsTo: "group", scaleType: "labels" },
        },
        pie: { alignment: "center" },
        donut: { alignment: "center" },
    });

    let chartType = $derived(widget.chartType);
</script>

<div class="chart-content">
    <div class="chart-wrapper">
        {#if error}
            <div class="error">{error}</div>
        {:else if loaded && chartData.length > 0}
            {#if chartType === "bar"}
                <BarChartSimple data={chartData} {options} />
            {:else if chartType === "line"}
                <LineChart data={chartData} {options} />
            {:else if chartType === "area"}
                <AreaChart data={chartData} {options} />
            {:else if chartType === "stacked-area"}
                <StackedAreaChart data={chartData} {options} />
            {:else if chartType === "pie"}
                <PieChart data={chartData} {options} />
            {:else if chartType === "donut"}
                <DonutChart data={chartData} {options} />
            {:else if chartType === "scatter"}
                <ScatterChart data={chartData} {options} />
            {:else}
                <BarChartSimple data={chartData} {options} />
            {/if}
        {:else if widget.loading}
            <div class="loading">Loading data...</div>
        {:else}
            <div class="empty">No data configured</div>
        {/if}
    </div>
    <DataInspectorFooter data={widget.chartData} />
</div>

<style>
    .chart-content {
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow: hidden;
    }
    .chart-wrapper {
        flex: 1;
        min-height: 0;
        padding: 10px;
        position: relative;
        overflow: hidden;
    }
    .chart-wrapper :global(.cds--cc--chart-wrapper) {
        height: 100%;
    }
    .error {
        color: var(--danger, red);
        padding: 20px;
        text-align: center;
    }
    .loading,
    .empty {
        color: var(--text-3, #999);
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
</style>
