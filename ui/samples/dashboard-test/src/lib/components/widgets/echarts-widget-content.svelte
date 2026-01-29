<script lang="ts">
    import { init } from "echarts";
    import type { BaseChartWidget } from "../../domain/base-chart-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";
    import { onMount } from "svelte";

    let { widget } = $props<{ widget: BaseChartWidget }>();

    // We will dynamically import echarts to avoid SSR/build issues if package is missing or problematic
    let Chart: any = $state(null);
    let error = $state("");

    onMount(async () => {
        try {
            const module = await import("svelte-echarts");
            Chart = module.Chart;
        } catch (e) {
            console.error("Failed to load svelte-echarts", e);
            error = "Failed to load Chart library";
        }
    });

    let options = $derived.by(() => {
        // ... (rest of logic is fine)
        const data = widget.chartData as Record<string, any>[];
        if (!data || data.length === 0) return {};

        const xAxisKey = widget.xAxis;
        const yAxisKey = widget.yAxis;
        const type = widget.chartType;

        const xData = xAxisKey ? data.map((d) => d[xAxisKey]) : [];
        const yData = yAxisKey ? data.map((d) => d[yAxisKey]) : [];

        // Basic ECharts Option mapping
        const base = {
            tooltip: { trigger: "axis" },
            grid: { top: 30, bottom: 30, left: 40, right: 20 },
            legend: { top: 0 },
        };

        if (["pie", "donut"].includes(type)) {
            const labelKey = widget.labelColumn || Object.keys(data[0])[0];
            const dataKey = widget.dataColumn || Object.keys(data[0])[1];

            return {
                ...base,
                tooltip: { trigger: "item" },
                series: [
                    {
                        type: "pie",
                        radius: type === "donut" ? ["40%", "70%"] : "50%",
                        data: data.map((d) => ({
                            name: d[labelKey],
                            value: d[dataKey],
                        })),
                    },
                ],
            };
        } else {
            // Cartesian
            return {
                ...base,
                tooltip: {
                    trigger: "axis",
                    axisPointer: { type: "shadow" },
                },
                xAxis: {
                    type: "category",
                    data: xData,
                    axisLabel: { interval: 0, rotate: 30 },
                },
                yAxis: { type: "value" },
                series: [
                    {
                        data: yData,
                        type:
                            type === "area" || type === "stacked-area"
                                ? "line"
                                : type,
                        areaStyle:
                            type === "area" || type === "stacked-area"
                                ? {}
                                : undefined,
                        smooth: true,
                        itemStyle: {
                            borderRadius: type === "bar" ? [4, 4, 0, 0] : 0,
                        },
                    },
                ],
            };
        }
    });
</script>

<div class="chart-content">
    <div class="chart-wrapper">
        {#if error}
            <div class="error">{error}</div>
        {:else if Chart && widget.chartData.length > 0}
            <Chart {init} {options} />
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
    }
    .chart-wrapper {
        flex: 1;
        min-height: 0;
        position: relative;
        padding: 10px;
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
