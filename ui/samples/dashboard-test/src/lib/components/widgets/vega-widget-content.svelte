<script lang="ts">
    import type { VegaChartWidget } from "../../domain/vega-chart-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";
    import { onMount } from "svelte";

    let { widget } = $props<{ widget: VegaChartWidget }>();

    let VegaLite: any = $state(null);
    let error = $state("");

    onMount(async () => {
        try {
            const module = await import("svelte-vega");
            VegaLite = module.VegaLite;
        } catch (e) {
            console.error("Failed to load svelte-vega", e);
            error = "Failed to load Vega library";
        }
    });

    let spec = $derived.by(() => {
        const type = widget.chartType;
        const x = widget.xAxis;
        const y = widget.yAxis;

        let mark: any = type;
        if (type === "scatter") mark = "point";
        if (type === "pie" || type === "donut") mark = "arc";
        if (type === "stacked-area") mark = "area";

        let encoding: any = {};

        if (["pie", "donut"].includes(type)) {
            const labelCol = widget.labelColumn;
            const dataCol = widget.dataColumn;
            encoding = {
                theta: { field: dataCol, type: "quantitative" },
                color: { field: labelCol, type: "nominal" },
            };
            if (type === "donut") {
                mark = { type: "arc", innerRadius: 50 };
            }
        } else {
            // Fallback if no axis selected
            const keys =
                widget.chartData.length > 0
                    ? Object.keys(widget.chartData[0])
                    : [];
            const xField = x || keys[0] || "";
            const yField = y || keys[1] || keys[0] || "";

            encoding = {
                x: { field: xField, type: "nominal", axis: { labelAngle: 0 } },
                y: { field: yField, type: "quantitative" },
            };
            if (type === "stacked-area") {
                // Stacked usually needs a color dimension, defaulting to just area if no color col config
                mark = "area";
            }
        }

        return {
            $schema: "https://vega.github.io/schema/vega-lite/v5.json",
            description: widget.title,
            data: { name: "table" }, // Data injected via options prop
            // width/height handled by options="container"
            autosize: { type: "fit", contains: "padding" },
            mark: mark,
            encoding: encoding,
        };
    });
</script>

<div class="chart-content">
    <div class="chart-wrapper">
        {#if error}
            <div class="error">{error}</div>
        {:else if VegaLite && widget.chartData.length > 0}
            <VegaLite
                data={{ table: widget.chartData }}
                {spec}
                options={{
                    actions: false,
                    width: "container",
                    height: "container",
                }}
            />
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
        padding: 10px;
        position: relative;
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
