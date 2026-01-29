
import { BaseChartWidget, type ChartWidgetConfig } from './base-chart-widget.svelte.js';

export class FrappeChartWidget extends BaseChartWidget {
    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Frappe Chart',
            icon: '📉'
        });
    }
}
