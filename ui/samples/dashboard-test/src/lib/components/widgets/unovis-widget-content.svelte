<script lang="ts">
    import type { UnovisChartWidget } from "../../domain/unovis-chart-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";
    import { onMount } from "svelte";

    let { widget } = $props<{ widget: UnovisChartWidget }>();

    // Unovis components - we load them dynamically or statically?
    // Statically is safer for Svelte components.
    // If usage fails, we wrap in try-catch dynamic import component loader pattern

    let VisXYContainer = $state<any>(null);
    let VisSingleContainer = $state<any>(null);
    let VisLine = $state<any>(null);
    let VisArea = $state<any>(null);
    let VisStackedBar = $state<any>(null);
    let VisGroupedBar = $state<any>(null);
    let VisScatter = $state<any>(null);
    let VisDonut = $state<any>(null);
    let VisAxis = $state<any>(null);
    let VisTooltip = $state<any>(null);

    let loaded = $state(false);
    let error = $state("");

    onMount(async () => {
        try {
            const module = await import("@unovis/svelte");
            VisXYContainer = module.VisXYContainer;
            VisSingleContainer = module.VisSingleContainer;
            VisLine = module.VisLine;
            VisArea = module.VisArea;
            VisStackedBar = module.VisStackedBar;
            VisGroupedBar = module.VisGroupedBar;
            VisScatter = module.VisScatter;
            VisDonut = module.VisDonut;
            VisAxis = module.VisAxis;
            VisTooltip = module.VisTooltip;
            loaded = true;
        } catch (e) {
            console.error("Failed to load @unovis/svelte", e);
            error =
                "Failed to load Unovis library. Ensure dependencies are installed.";
        }
    });

    let x = $derived((d: any, i: number) => {
        if (!widget.xAxis) return i;
        return String(d[widget.xAxis]);
    });
    let y = $derived((d: any) => {
        if (!widget.yAxis) return 0;
        const val = Number(d[widget.yAxis]);
        return isNaN(val) ? 0 : val;
    });

    let chartType = $derived(widget.chartType);
</script>

<div class="chart-content">
    <div class="chart-wrapper">
        {#if error}
            <div class="error">{error}</div>
        {:else if loaded && widget.chartData.length > 0}
            {#if ["pie", "donut"].includes(chartType)}
                <VisSingleContainer data={widget.chartData} height={300}>
                    <VisDonut
                        value={(d: any) =>
                            widget.dataColumn ? d[widget.dataColumn] : 0}
                        arcWidth={chartType === "donut" ? 40 : 0}
                    />
                    <VisTooltip />
                </VisSingleContainer>
            {:else}
                <VisXYContainer
                    data={widget.chartData}
                    height={"100%"}
                    scale={{
                        x: { type: "band" },
                    }}
                >
                    {#if chartType === "line"}
                        <VisLine {x} {y} duration={0} />
                    {:else if chartType === "area"}
                        <VisArea {x} {y} duration={0} />
                    {:else if chartType === "bar"}
                        <!-- GroupedBar for simple bar chart -->
                        <VisGroupedBar {x} {y} duration={0} />
                    {:else if chartType === "stacked-area"}
                        <VisArea {x} {y} duration={0} />
                    {:else if chartType === "scatter"}
                        <VisScatter {x} {y} duration={0} />
                    {/if}
                    <VisAxis type="x" {x} />
                    <VisAxis type="y" />
                    <VisTooltip />
                </VisXYContainer>
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
        width: 100%;
    }
    .chart-wrapper {
        flex: 1;
        min-height: 200px;
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
