
import { BaseChartWidget, type ChartWidgetConfig } from "./base-chart-widget.svelte.js";

export class LayerChartWidget extends BaseChartWidget {
    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? "Layer Chart",
            icon: config.icon ?? "📈",
        });
    }
}
