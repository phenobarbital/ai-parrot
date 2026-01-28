/**
 * QSWidget - A Widget that displays data from QuerySource.
 */

import { Widget, type WidgetConfig } from './widget.svelte.js';
import { QSDataSource, type QSDataSourceConfig } from './qs-datasource.svelte.js';

export interface QSWidgetConfig extends Omit<WidgetConfig, 'dataSource'> {
    qsConfig: QSDataSourceConfig;
}

export class QSWidget extends Widget {
    qsDataSource: QSDataSource;

    constructor(config: QSWidgetConfig) {
        super({
            ...config,
            icon: config.icon ?? '⚡',
        });

        this.qsDataSource = new QSDataSource(config.qsConfig);

        // We set the base dataSource property to point to our specific one
        // so generic widget logic (like auto-refresh) works if it uses the base interface
        // We set the base dataSource property to point to our specific one
        // so generic widget logic (like auto-refresh) works if it uses the base interface
        this.setDataSource(this.qsDataSource.config as any);
    }

    /**
     * Override to sync specific QS config changes
     */
    setQSConfig(config: QSDataSourceConfig) {
        this.qsDataSource = new QSDataSource(config);
        // @ts-ignore
        this.setDataSource(this.qsDataSource.config);
    }
}
