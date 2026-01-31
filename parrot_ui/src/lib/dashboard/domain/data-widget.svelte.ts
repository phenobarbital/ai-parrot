/**
 * DataWidget - A Widget that displays data from a REST API.
 * Used for testing the DataSource integration.
 */

import { Widget, type WidgetConfig } from './widget.svelte.js';
import type { DataSourceConfig } from './data-source.svelte.js';

export interface DataWidgetConfig extends Omit<WidgetConfig, 'dataSource'> {
    dataSource: DataSourceConfig;
}

export class DataWidget extends Widget {
    constructor(config: DataWidgetConfig) {
        super({
            ...config,
            icon: config.icon ?? '📡',
        });
    }

    /**
     * Override to log and render data.
     */
    override onDataLoaded(data: unknown): void {
        console.log(`[DataWidget:${this.id}] Data loaded:`, data);
        // Data is now available via this.data
    }

    /**
     * Override to handle errors.
     */
    override onLoadError(error: Error): void {
        super.onLoadError(error as any);
        console.error(`[DataWidget:${this.id}] Load error:`, error);
    }
}
