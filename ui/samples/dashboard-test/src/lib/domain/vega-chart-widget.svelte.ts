
import { BaseChartWidget, type ChartWidgetConfig } from './base-chart-widget.svelte.js';

export class VegaChartWidget extends BaseChartWidget {
    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Vega Chart',
            icon: '📊'
        });
    }
}
