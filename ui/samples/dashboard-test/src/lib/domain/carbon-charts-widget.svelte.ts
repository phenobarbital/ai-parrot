
import { BaseChartWidget, type ChartWidgetConfig } from './base-chart-widget.svelte.js';

export class CarbonChartsWidget extends BaseChartWidget {
    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Carbon Chart',
            icon: '📊'
        });
    }
}
