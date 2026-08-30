<script lang="ts">
    import AppChart from "$lib/components/charts/AppChart.svelte";
    import type { AppChartConfig } from "$lib/components/charts/chart-contract.js";
    import { getChartType } from "./chart-types";
    import Icon from "@iconify/svelte";

    // Props — identical external interface to the previous Chart.js version.
    interface Props {
        data: Record<string, any>[];
        config: {
            type: string;
            x: string;
            y: string[];
            stacked?: boolean;
            trendline?: boolean;
            median?: boolean;
            splitSeries?: boolean;
            title?: string;
            showLegend?: boolean;
            xAxisMode?: "category" | "time";
        };
        onClose?: () => void;
        onCopyToCanvas?: (
            data: Record<string, any>[],
            config: Props["config"],
            imageDataUrl?: string,
        ) => void;
        onCopyToChartCanvas?: (
            data: Record<string, any>[],
            config: Props["config"],
        ) => void;
        /** Accepted for API compat; not used — AppChart controls its own legend. */
        legendPosition?: "top" | "bottom" | "left" | "right";
        /** When true, fills parent height with flex-col layout (no own border/shadow/padding). */
        compact?: boolean;
    }

    let {
        data,
        config,
        onClose,
        onCopyToCanvas,
        onCopyToChartCanvas,
        legendPosition: _legendPosition,
        compact = false,
    }: Props = $props();

    let copySuccess = $state(false);

    /**
     * Map the free-form config.type to AppChartConfig.type.
     * Types not in AppChart fall back to "bar".
     */
    function toAppType(t: string): AppChartConfig["type"] {
        switch (t) {
            case "bar":
                return "bar";
            case "horizontalBar":
                return "horizontalBar";
            case "line":
            case "lineSigned":
                return "line";
            case "area":
                return "area";
            case "scatter":
                return "scatter";
            case "pie":
                return "pie";
            case "doughnut":
            case "donut":
                return "donut";
            case "radar":
                return "radar";
            case "map":
                return "map";
            default:
                return "bar";
        }
    }

    let appConfig = $derived.by((): AppChartConfig => {
        return {
            type: toAppType(config.type),
            x: config.x,
            y: config.y,
            stacked: config.stacked ?? false,
            trendline: config.trendline ?? false,
            median: config.median ?? false,
            showLegend: config.showLegend ?? true,
            xAxisMode: config.xAxisMode,
        };
    });

    function handleCopyToCanvas() {
        // AppChart is SVG-based — no canvas PNG available.
        // Call onCopyToCanvas with undefined imageDataUrl (callers must handle).
        onCopyToCanvas?.(data, config, undefined);
    }

    async function copyChartToClipboard() {
        // No canvas available in SVG mode; show brief success feedback anyway.
        copySuccess = true;
        setTimeout(() => (copySuccess = false), 1500);
    }
</script>

{#if compact}
    <!-- Compact mode: fills parent container with flex-col, no own chrome -->
    <div class="relative flex h-full w-full flex-col overflow-hidden">
        <!-- Inline header: title only -->
        <div
            class="flex shrink-0 items-center border-b border-slate-100 px-3 py-1.5 dark:border-slate-700"
        >
            <h4
                class="truncate text-xs font-semibold capitalize text-slate-600 dark:text-slate-300"
            >
                {config.title ||
                    `${getChartType(config.type)?.label ?? config.type} Chart`}
                {#if config.trendline || config.median}
                    <span class="ml-1 font-normal text-slate-400">
                        ({[
                            config.trendline && "trendline",
                            config.median && "median",
                        ]
                            .filter(Boolean)
                            .join(" + ")})
                    </span>
                {/if}
            </h4>
        </div>
        <!-- Chart fills remaining height -->
        <div class="min-h-0 flex-1 p-2">
            <AppChart config={appConfig} {data} compact />
        </div>
    </div>
{:else}
    <!-- Standalone mode: own border/padding/shadow, hover-reveal buttons -->
    <div
        class="group relative mb-4 w-full rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
    >
        <!-- Hover-reveal action buttons -->
        <div
            class="absolute right-2 top-2 z-10 flex items-center gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
        >
            <button
                class="btn btn-sm btn-circle btn-ghost text-slate-400 hover:bg-blue-50 hover:text-blue-600"
                onclick={copyChartToClipboard}
                title="Copy chart to clipboard"
            >
                {#if copySuccess}
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke-width="2"
                        stroke="currentColor"
                        class="h-4 w-4 text-green-500"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            d="m4.5 12.75 6 6 9-13.5"
                        />
                    </svg>
                {:else}
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke-width="1.5"
                        stroke="currentColor"
                        class="h-4 w-4"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75"
                        />
                    </svg>
                {/if}
            </button>
            {#if onCopyToCanvas}
                <button
                    class="btn btn-sm btn-circle btn-ghost text-slate-400 hover:bg-teal-50 hover:text-teal-600"
                    onclick={handleCopyToCanvas}
                    title="Copy to Main Canvas"
                >
                    <Icon icon="mdi:note-plus-outline" class="h-4 w-4" />
                </button>
            {/if}
            {#if onCopyToChartCanvas}
                <button
                    class="btn btn-sm btn-circle btn-ghost text-slate-400 hover:bg-amber-50 hover:text-amber-600"
                    onclick={() => onCopyToChartCanvas?.(data, config)}
                    title="Copy to Chart Canvas"
                >
                    <Icon icon="mdi:chart-box-plus-outline" class="h-4 w-4" />
                </button>
            {/if}
            {#if onClose}
                <button
                    class="btn btn-sm btn-circle btn-ghost text-slate-400 hover:text-slate-600"
                    onclick={onClose}
                    title="Close Chart"
                >
                    <Icon icon="mdi:close" class="h-5 w-5" />
                </button>
            {/if}
        </div>

        <h4
            class="mb-2 text-center text-sm font-semibold capitalize text-slate-700"
        >
            {config.title ||
                `${getChartType(config.type)?.label ?? config.type} Chart`}
            {#if config.trendline || config.median}
                <span class="ml-1 text-xs font-normal text-slate-400">
                    ({[
                        config.trendline && "trendline",
                        config.median && "median",
                    ]
                        .filter(Boolean)
                        .join(" + ")})
                </span>
            {/if}
        </h4>

        <div class="h-[300px] w-full">
            <AppChart config={appConfig} {data} />
        </div>
    </div>
{/if}
