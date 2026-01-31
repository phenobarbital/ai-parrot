
import { Widget, type WidgetConfig } from './widget.svelte.js';
import { DataSource, type DataSourceConfig } from './data-source.svelte.js';
import { QSDataSource, type QSDataSourceConfig } from './qs-datasource.svelte.js';

export type ChartType = 'line' | 'bar' | 'area' | 'stacked-area' | 'pie' | 'donut' | 'scatter';

export interface ChartWidgetConfig extends Omit<WidgetConfig, 'dataSource'> {
    chartType?: ChartType;
    xAxis?: string;
    yAxis?: string;
    labelColumn?: string; // For pie/donut
    dataColumn?: string;  // For pie/donut

    // Data Source Config
    dataSourceType?: 'rest' | 'qs' | 'json';
    restConfig?: DataSourceConfig;
    qsConfig?: QSDataSourceConfig;
    jsonConfig?: { mode: 'inline' | 'url', json?: string, url?: string };
}

export class BaseChartWidget extends Widget {
    chartType = $state<ChartType>('bar');
    xAxis = $state<string>('');
    yAxis = $state<string>('');
    labelColumn = $state<string>('');
    dataColumn = $state<string>('');

    // Data handling similar to SimpleTableWidget
    #dataSourceType = $state<'rest' | 'qs' | 'json'>('json');
    #restConfig = $state<DataSourceConfig | null>(null);
    #qsConfig = $state<QSDataSourceConfig | null>(null);
    #jsonConfig = $state<{ mode: 'inline' | 'url', json?: string, url?: string }>({ mode: 'inline', json: '[]' });

    #chartData = $state<unknown[]>([]);

    constructor(config: ChartWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Chart Widget',
            icon: config.icon ?? '📊',
        });

        this.chartType = config.chartType ?? 'bar';
        this.xAxis = config.xAxis ?? '';
        this.yAxis = config.yAxis ?? '';
        this.labelColumn = config.labelColumn ?? '';
        this.dataColumn = config.dataColumn ?? '';

        this.#dataSourceType = config.dataSourceType ?? 'json';
        this.#restConfig = config.restConfig ?? null;
        this.#qsConfig = config.qsConfig ?? null;
        this.#jsonConfig = config.jsonConfig ?? { mode: 'inline', json: '[]' };
    }

    // Getters
    get dataSourceType() { return this.#dataSourceType; }
    get restConfig() { return this.#restConfig; }
    get qsConfig() { return this.#qsConfig; }
    get jsonConfig() { return this.#jsonConfig; }
    get chartData() { return this.#chartData; }

    // Setters
    setDataSourceType(type: 'rest' | 'qs' | 'json') { this.#dataSourceType = type; }

    setRestConfig(config: DataSourceConfig) {
        this.#restConfig = config;
        // Logic to update active data source could go here if we used Widget's own dataSource
    }

    setQSConfig(config: QSDataSourceConfig) { this.#qsConfig = config; }
    setJsonConfig(config: { mode: 'inline' | 'url', json?: string, url?: string }) { this.#jsonConfig = config; }

    setChartConfig(config: { chartType?: ChartType, xAxis?: string, yAxis?: string, labelColumn?: string, dataColumn?: string }) {
        if (config.chartType) this.chartType = config.chartType;
        if (config.xAxis !== undefined) this.xAxis = config.xAxis;
        if (config.yAxis !== undefined) this.yAxis = config.yAxis;
        if (config.labelColumn !== undefined) this.labelColumn = config.labelColumn;
        if (config.dataColumn !== undefined) this.dataColumn = config.dataColumn;
    }

    // Load Data - Reusing logic from SimpleTableWidget
    async loadData(): Promise<void> {
        this.loading = true;
        this.error = null;

        try {
            let data: unknown[];
            switch (this.#dataSourceType) {
                case 'rest':
                    if (!this.#restConfig?.url) throw new Error('REST URL is required');
                    const ds = new DataSource(this.#restConfig);
                    data = await ds.fetch();
                    break;
                case 'qs':
                    if (!this.#qsConfig?.slug) throw new Error('QuerySource slug is required');
                    const qs = new QSDataSource(this.#qsConfig);
                    data = await qs.fetch();
                    break;
                case 'json':
                    if (this.#jsonConfig.mode === 'inline') {
                        data = JSON.parse(this.#jsonConfig.json ?? '[]');
                    } else if (this.#jsonConfig.mode === 'url' && this.#jsonConfig.url) {
                        const res = await fetch(this.#jsonConfig.url);
                        if (!res.ok) throw new Error(`Failed: ${res.status}`);
                        data = await res.json();
                    } else {
                        data = [];
                    }
                    break;
                default:
                    data = [];
            }
            this.#chartData = Array.isArray(data) ? data : [];
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            this.error = message;
            console.error(`[ChartWidget] Load error:`, err);
        } finally {
            this.loading = false;
        }
    }
}
