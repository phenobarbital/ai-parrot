/**
 * SimpleTableWidget - Widget that displays tabular data with zebra striping, masks, and totals.
 * Supports multiple data sources: REST, QuerySource, or inline/URL JSON.
 */

import { Widget, type WidgetConfig } from './widget.svelte.js';
import { DataSource, type DataSourceConfig } from './data-source.svelte.js';
import { QSDataSource, type QSDataSourceConfig, DEFAULT_QS_URL } from './qs-datasource.svelte.js';

// ============================================================================
// Types
// ============================================================================

export type TotalType = 'sum' | 'avg' | 'median' | 'none';
export type DataSourceType = 'rest' | 'qs' | 'json';

export interface ColumnConfig {
    key: string;
    label?: string;
    mask?: 'money' | 'number' | 'percent' | 'string';
    hidden?: boolean;
    summarize?: boolean;
}

export interface JsonDataSourceConfig {
    mode: 'inline' | 'url';
    json?: string;      // For inline mode
    url?: string;       // For URL mode
}

export interface SimpleTableWidgetConfig extends Omit<WidgetConfig, 'dataSource'> {
    dataSourceType?: DataSourceType;
    restConfig?: DataSourceConfig;
    qsConfig?: QSDataSourceConfig;
    jsonConfig?: JsonDataSourceConfig;
    zebra?: boolean;
    totals?: TotalType;
    columns?: ColumnConfig[];
}

// ============================================================================
// SimpleTableWidget
// ============================================================================

export class SimpleTableWidget extends Widget {
    // Data source management
    #dataSourceType = $state<DataSourceType>('json');
    #restConfig = $state<DataSourceConfig | null>(null);
    #qsConfig = $state<QSDataSourceConfig | null>(null);
    #jsonConfig = $state<JsonDataSourceConfig>({ mode: 'inline', json: '[]' });

    // Active data source instance
    #activeDataSource: DataSource | QSDataSource | null = null;

    // Table configuration
    #zebra = $state(true);
    #totals = $state<TotalType>('none');
    #columns = $state<ColumnConfig[]>([]);

    // Loaded data
    #tableData = $state<unknown[]>([]);

    constructor(config: SimpleTableWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Simple Table',
            icon: config.icon ?? '▦',
        });

        // Initialize from config
        this.#dataSourceType = config.dataSourceType ?? 'json';
        this.#restConfig = config.restConfig ?? null;
        this.#qsConfig = config.qsConfig ?? null;
        this.#jsonConfig = config.jsonConfig ?? { mode: 'inline', json: '[]' };
        this.#zebra = config.zebra ?? true;
        this.#totals = config.totals ?? 'none';
        this.#columns = config.columns ?? [];
    }

    // === Getters ===

    get dataSourceType(): DataSourceType {
        return this.#dataSourceType;
    }

    get restConfig(): DataSourceConfig | null {
        return this.#restConfig;
    }

    get qsConfig(): QSDataSourceConfig | null {
        return this.#qsConfig;
    }

    get jsonConfig(): JsonDataSourceConfig {
        return this.#jsonConfig;
    }

    get zebra(): boolean {
        return this.#zebra;
    }

    get totals(): TotalType {
        return this.#totals;
    }

    get columns(): ColumnConfig[] {
        return this.#columns;
    }

    get tableData(): unknown[] {
        return this.#tableData;
    }

    // === Configuration Setters ===

    setDataSourceType(type: DataSourceType): void {
        this.#dataSourceType = type;
    }

    setRestConfig(config: DataSourceConfig): void {
        this.#restConfig = config;
        if (this.#dataSourceType === 'rest') {
            this.#activeDataSource = new DataSource(config);
        }
    }

    setQSConfig(config: QSDataSourceConfig): void {
        this.#qsConfig = config;
        if (this.#dataSourceType === 'qs') {
            this.#activeDataSource = new QSDataSource(config);
        }
    }

    setJsonConfig(config: JsonDataSourceConfig): void {
        this.#jsonConfig = config;
    }

    setTableConfig(config: { zebra?: boolean; totals?: TotalType; columns?: ColumnConfig[] }): void {
        if (config.zebra !== undefined) this.#zebra = config.zebra;
        if (config.totals !== undefined) this.#totals = config.totals;
        if (config.columns !== undefined) this.#columns = config.columns;
    }

    // === Data Loading ===

    async loadData(): Promise<void> {
        this.loading = true;
        this.error = null;

        try {
            let data: unknown[];

            switch (this.#dataSourceType) {
                case 'rest':
                    data = await this.#loadFromRest();
                    break;
                case 'qs':
                    data = await this.#loadFromQS();
                    break;
                case 'json':
                    data = await this.#loadFromJson();
                    break;
                default:
                    data = [];
            }

            this.#tableData = Array.isArray(data) ? data : [];
            this.onDataLoaded(this.#tableData);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            this.error = message;
            console.error(`[SimpleTableWidget:${this.id}] Load error:`, err);
        } finally {
            this.loading = false;
        }
    }

    async #loadFromRest(): Promise<unknown[]> {
        if (!this.#restConfig?.url) {
            throw new Error('REST URL is required');
        }
        const ds = new DataSource(this.#restConfig);
        const result = await ds.fetch();
        return Array.isArray(result) ? result : [];
    }

    async #loadFromQS(): Promise<unknown[]> {
        if (!this.#qsConfig?.slug) {
            throw new Error('QuerySource slug is required');
        }
        const ds = new QSDataSource(this.#qsConfig);
        const result = await ds.fetch();
        return Array.isArray(result) ? result : [];
    }

    async #loadFromJson(): Promise<unknown[]> {
        const config = this.#jsonConfig;

        if (config.mode === 'inline') {
            const json = config.json ?? '[]';
            const parsed = JSON.parse(json);
            return Array.isArray(parsed) ? parsed : [];
        } else if (config.mode === 'url' && config.url) {
            const response = await fetch(config.url);
            if (!response.ok) {
                throw new Error(`Failed to fetch JSON: ${response.status}`);
            }
            const data = await response.json();
            return Array.isArray(data) ? data : [];
        }

        return [];
    }

    // === Utility Functions (for rendering) ===

    /**
     * Format a value based on mask type.
     */
    formatValue(value: unknown, mask?: string): string {
        if (value === null || value === undefined) return '';

        // Handle objects - stringify them
        if (typeof value === 'object') {
            return JSON.stringify(value);
        }

        if (typeof value !== 'number') return String(value);

        switch (mask) {
            case 'money':
                return value.toLocaleString(undefined, { style: 'currency', currency: 'USD' });
            case 'percent':
                return value.toLocaleString(undefined, { style: 'percent', minimumFractionDigits: 1 });
            case 'number':
                return value.toLocaleString();
            default:
                return String(value);
        }
    }

    /**
     * Calculate total for a column.
     */
    calculateTotal(values: number[], type: TotalType): number {
        if (values.length === 0) return 0;
        const sum = values.reduce((a, b) => a + b, 0);

        switch (type) {
            case 'sum':
                return sum;
            case 'avg':
                return sum / values.length;
            case 'median': {
                const sorted = [...values].sort((a, b) => a - b);
                const mid = Math.floor(sorted.length / 2);
                return sorted.length % 2 !== 0 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
            }
            default:
                return 0;
        }
    }

    /**
     * Humanize a key string.
     */
    humanize(key: string): string {
        return key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
    }

    /**
     * Get effective columns (auto-detect if not configured).
     */
    getEffectiveColumns(): ColumnConfig[] {
        if (this.#columns.length > 0) {
            return this.#columns;
        }

        // Auto-detect from first row
        if (this.#tableData.length > 0) {
            const firstRow = this.#tableData[0] as Record<string, unknown>;
            return Object.keys(firstRow).map((key) => ({
                key,
                label: this.humanize(key),
            }));
        }

        return [];
    }
}
