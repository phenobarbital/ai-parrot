import { BaseChartWidget, type ChartWidgetConfig } from "./base-chart-widget.svelte.js";

export type ChartEngine = "carbon" | "echarts" | "vega" | "frappe";

export interface BasicChartWidgetConfig extends ChartWidgetConfig {
    chartEngine?: ChartEngine;
}

const isChartEngine = (value: unknown): value is ChartEngine =>
    value === "carbon" || value === "echarts" || value === "vega" || value === "frappe";

export class BasicChartWidget extends BaseChartWidget {
    chartEngine = $state<ChartEngine>("carbon");

    constructor(config: BasicChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? "Basic Chart",
            icon: config.icon ?? "📊",
        });

        this.chartEngine = config.chartEngine ?? "carbon";
    }

    setChartEngine(engine: ChartEngine): void {
        this.chartEngine = engine;
    }

    override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);
        if (isChartEngine(config.chartEngine)) {
            this.chartEngine = config.chartEngine;
        }
    }
}
