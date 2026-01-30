<script lang="ts">
    import { onMount } from "svelte";
    import { LayerChartWidget } from "../../domain/layer-chart-widget.svelte.js";
    import {
        Chart,
        Svg,
        Axis,
        Bars,
        Spline,
        Area,
        Highlight,
        Tooltip,
        Pie,
        Group,
    } from "layerchart";
    import { scaleBand, scaleLinear, scaleTime, scaleOrdinal } from "d3-scale";
    import { format } from "date-fns";

    interface Props {
        widget: LayerChartWidget;
    }

    let { widget }: Props = $props();

    // Chart Type Logic
    let isPie = $derived(
        widget.chartType === "pie" || widget.chartType === "donut",
    );
    let isLine = $derived(
        widget.chartType === "line" || widget.chartType === "area",
    );
    let isBar = $derived(!isPie && !isLine); // Default to bar

    // Data Processing
    let data = $derived.by(() => {
        if (!widget.chartData || widget.chartData.length === 0) return [];

        return widget.chartData.map((row: any) => {
            // Try to find the X/Group Key
            const xKey = widget.xAxis || "date" || "name" || "id" || "group";
            const yKey = widget.yAxis || "value" || "count";

            let xVal = row[xKey];
            // Auto-detect dates if xKey contains "date" or "time"
            if (
                typeof xKey === "string" &&
                (xKey.includes("date") || xKey.includes("time")) &&
                typeof xVal === "string"
            ) {
                xVal = new Date(xVal);
            } else if (isPie) {
                // For Pie, use name/label preferentially
                xVal =
                    row[widget.labelColumn || "name" || "label"] ??
                    xVal ??
                    "Unknown";
            } else {
                xVal = xVal ?? "Unknown";
            }

            const yVal = Number(row[yKey] ?? 0);

            return {
                group: xVal,
                value: yVal,
                original: row,
            };
        });
    });

    let containerWidth = $state(0);
    let containerHeight = $state(0);
</script>

<div
    class="h-full w-full p-2 box-border"
    bind:clientWidth={containerWidth}
    bind:clientHeight={containerHeight}
>
    {#if containerWidth > 0 && containerHeight > 0}
        {#if data.length > 0}
            <div class="h-full w-full relative">
                <Chart
                    {data}
                    x="group"
                    xScale={isPie
                        ? undefined
                        : data[0]?.group instanceof Date
                          ? scaleTime()
                          : scaleBand().padding(0.4)}
                    y="value"
                    yScale={isPie ? undefined : scaleLinear()}
                    yDomain={[0, null]}
                    yNice
                    padding={{ left: 16, bottom: 24, right: 16, top: 16 }}
                    tooltip={{ mode: isPie ? "manual" : "band" }}
                >
                    <Svg>
                        <!-- Axis (only for Cartesian) -->
                        {#if !isPie}
                            <Axis placement="left" grid rule />
                            <Axis
                                placement="bottom"
                                rule
                                format={(d) => {
                                    if (d instanceof Date)
                                        return format(d, "MMM d");
                                    return d;
                                }}
                            />
                        {/if}

                        <!-- Visualization -->
                        {#if isBar}
                            <Bars
                                radius={4}
                                strokeWidth={1}
                                class="fill-primary/80 transition-all duration-300 hover:fill-primary"
                            />
                        {:else if isLine}
                            {#if widget.chartType === "area"}
                                <Area
                                    class="fill-primary/20"
                                    line={{ class: "stroke-primary stroke-2" }}
                                />
                            {:else}
                                <Spline class="stroke-primary stroke-2" />
                            {/if}
                        {:else if isPie}
                            <Group center>
                                <Pie
                                    innerRadius={widget.chartType === "donut"
                                        ? 0.6
                                        : 0}
                                    outerRadius={0.8}
                                    cornerRadius={4}
                                    padAngle={0.02}
                                >
                                    <!-- Use slot prop pattern for Arc correctly if typically used, or standard -->
                                </Pie>
                            </Group>
                        {/if}

                        {#if !isPie}
                            <Highlight area />
                        {/if}
                    </Svg>

                    <!-- Tooltips -->
                    <Tooltip.Root let:data>
                        <Tooltip.Header
                            >{data.group instanceof Date
                                ? format(data.group, "PP")
                                : data.group}</Tooltip.Header
                        >
                        <Tooltip.List>
                            <Tooltip.Item label="Value" value={data.value} />
                        </Tooltip.List>
                    </Tooltip.Root>
                </Chart>
            </div>
        {:else}
            <div class="flex h-full items-center justify-center text-gray-400">
                No data available
            </div>
        {/if}
    {/if}
</div>
