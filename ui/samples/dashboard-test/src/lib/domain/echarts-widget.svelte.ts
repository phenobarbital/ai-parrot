
import { BaseChartWidget, type ChartWidgetConfig } from './base-chart-widget.svelte.js';

export class EchartsWidget extends BaseChartWidget {
    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'ECharts Widget',
            icon: '📈'
        });
    }
}
