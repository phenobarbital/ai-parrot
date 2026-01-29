
import { BaseChartWidget, type ChartWidgetConfig } from './base-chart-widget.svelte.js';

export class UnovisChartWidget extends BaseChartWidget {
    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Unovis Chart',
            icon: '🕸️'
        });
    }
}
