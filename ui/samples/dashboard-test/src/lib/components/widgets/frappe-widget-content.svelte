<script lang="ts">
    import type { BaseChartWidget } from "../../domain/base-chart-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";
    import { onMount, onDestroy } from "svelte";

    // Frappe Charts is browser-only
    let { widget } = $props<{ widget: BaseChartWidget }>();

    let chartContainer: HTMLElement;
    let chartInstance = $state<any>(null);
    let error = $state("");

    async function renderChart() {
        if (!chartContainer || !widget.chartData.length) return;

        try {
            // dynamic import
            // @ts-ignore
            const module = await import("frappe-charts");
            const { Chart } = module;

            const data = widget.chartData as Record<string, any>[];
            const type =
                widget.chartType === "area" ||
                widget.chartType === "stacked-area"
                    ? "line"
                    : widget.chartType; // Frappe has axis-mixed but let's map simply
            // Frappe types: 'bar', 'line', 'scatter', 'pie', 'percentage', 'heatmap'

            let labels: string[] = [];
            let values: number[] = [];

            if (["pie", "donut"].includes(widget.chartType)) {
                // Frappe 'percentage' is closest to donut? Or just 'pie'.
                // For pie, data format is different? Frappe docs say same structure usually.
                const labelCol = widget.labelColumn || Object.keys(data[0])[0];
                const dataCol = widget.dataColumn || Object.keys(data[0])[1];
                labels = data.map((d) => String(d[labelCol]));
                values = data.map((d) => Number(d[dataCol]));
            } else {
                const xCol = widget.xAxis || Object.keys(data[0])[0];
                const yCol = widget.yAxis || Object.keys(data[0])[1];
                labels = data.map((d) => String(d[xCol]));
                values = data.map((d) => Number(d[yCol]));
            }

            const chartData = {
                labels: labels,
                datasets: [
                    {
                        name: widget.title,
                        values: values,
                        chartType: type,
                    },
                ],
            };

            if (chartInstance) {
                chartInstance.update(chartData);
            } else {
                chartInstance = new Chart(chartContainer, {
                    title: "", // Hide default title
                    data: chartData,
                    type: type === "donut" ? "percentage" : type,
                    height: chartContainer.clientHeight || 300,
                    colors: ["#7cd6fd", "#743ee2"],
                });
            }
        } catch (e) {
            console.error(e);
            error = "Failed to load Frappe Charts";
        }
    }

    $effect(() => {
        // React to data or config changes
        if (widget.chartData && widget.chartType) {
            renderChart();
        }
    });

    onMount(() => {
        renderChart();
    });

    onDestroy(() => {
        if (chartInstance) {
            // chartInstance.destroy(); // Frappe might not have destroy
            chartInstance = null;
        }
    });
</script>

<div class="chart-content">
    <div class="chart-wrapper" bind:this={chartContainer}>
        {#if error}<div class="error">{error}</div>{/if}
        {#if !chartInstance && !error && widget.chartData.length === 0}
            <div class="empty">No data</div>
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
        padding: 0;
        overflow: hidden;
    }
    .error {
        color: var(--danger, red);
        padding: 20px;
        text-align: center;
    }
    .empty {
        color: var(--text-3, #999);
        text-align: center;
        padding: 20px;
    }
</style>
