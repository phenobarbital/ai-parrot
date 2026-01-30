<script lang="ts">
    import type { BaseChartWidget } from "../../domain/base-chart-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";
    import { onMount } from "svelte";

    let { widget } = $props<{ widget: BaseChartWidget }>();

    let VegaLite: any = $state(null);
    let error = $state("");
    let chartWrapper: HTMLDivElement | null = $state(null);
    let containerWidth = $state(400);
    let containerHeight = $state(300);

    onMount(async () => {
        try {
            const module = await import("svelte-vega");
            VegaLite = module.VegaLite;
        } catch (e) {
            console.error("Failed to load svelte-vega", e);
            error = "Failed to load Vega library";
        }

        // Measure container size
        if (chartWrapper) {
            const resizeObserver = new ResizeObserver((entries) => {
                for (const entry of entries) {
                    containerWidth = Math.max(
                        entry.contentRect.width - 40,
                        100,
                    );
                    containerHeight = Math.max(
                        entry.contentRect.height - 40,
                        100,
                    );
                }
            });
            resizeObserver.observe(chartWrapper);
            return () => resizeObserver.disconnect();
        }
    });

    // Build the Vega-Lite spec with inline data and dynamic sizing
    let spec = $derived.by(() => {
        const type = widget.chartType;
        const xCol = widget.xAxis;
        const yCol = widget.yAxis;

        // Fallback to first columns if not set
        const keys =
            widget.chartData.length > 0
                ? Object.keys(widget.chartData[0] as object)
                : [];
        const xField = xCol || keys[0] || "x";
        const yField = yCol || keys[1] || keys[0] || "y";

        let mark: any = type;
        if (type === "scatter") mark = "point";
        if (type === "pie" || type === "donut") mark = "arc";
        if (type === "stacked-area") mark = "area";

        let encoding: any = {};

        if (["pie", "donut"].includes(type)) {
            const labelCol = widget.labelColumn || xField;
            const dataCol = widget.dataColumn || yField;
            encoding = {
                theta: { field: dataCol, type: "quantitative" },
                color: { field: labelCol, type: "nominal" },
            };
            if (type === "donut") {
                mark = { type: "arc", innerRadius: 50 };
            }
        } else {
            encoding = {
                x: {
                    field: xField,
                    type: "nominal",
                    axis: { labelAngle: -45 },
                },
                y: { field: yField, type: "quantitative" },
            };
        }

        return {
            $schema: "https://vega.github.io/schema/vega-lite/v5.json",
            description: widget.title,
            data: { values: widget.chartData },
            width: containerWidth,
            height: containerHeight,
            autosize: { type: "fit", contains: "padding" },
            mark: mark,
            encoding: encoding,
        };
    });
</script>

<div class="chart-content">
    <div class="chart-wrapper" bind:this={chartWrapper}>
        {#if error}
            <div class="error">{error}</div>
        {:else if VegaLite && widget.chartData.length > 0}
            <VegaLite {spec} options={{ actions: false, renderer: "svg" }} />
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
        display: flex;
        align-items: center;
        justify-content: center;
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
