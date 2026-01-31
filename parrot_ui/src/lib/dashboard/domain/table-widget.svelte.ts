/**
 * TableWidget - Widget that displays tabular data using various grid libraries.
 * Supports: Grid.js, AG-Grid, RevoGrid, and a native Simple Table.
 */

import { Widget, type WidgetConfig } from './widget.svelte.js';
import { DataSource, type DataSourceConfig } from './data-source.svelte.js';
import { QSDataSource, type QSDataSourceConfig } from './qs-datasource.svelte.js';

// ============================================================================
// Types
// ============================================================================

export type GridType = 'gridjs' | 'tabulator' | 'revogrid' | 'powertable' | 'flowbite' | 'simple';

export type DataSourceType = 'rest' | 'qs' | 'json';

export interface JsonDataSourceConfig {
    mode: 'inline' | 'url';
    json?: string;
    url?: string;
}

export interface ColumnDef {
    field: string;
    headerName?: string;
    width?: number;
    sortable?: boolean;
    filter?: boolean;
}

export interface GridConfig {
    pagination?: boolean;
    pageSize?: number;
    sortable?: boolean;
    filterable?: boolean;
    resizable?: boolean;
}

export interface TableWidgetConfig extends Omit<WidgetConfig, 'dataSource'> {
    gridType?: GridType;
    dataSourceType?: DataSourceType;
    restConfig?: DataSourceConfig;
    qsConfig?: QSDataSourceConfig;
    jsonConfig?: JsonDataSourceConfig;
    columns?: ColumnDef[];
    gridConfig?: GridConfig;
}

// ============================================================================
// TableWidget
// ============================================================================

export class TableWidget extends Widget {
    // Grid type
    #gridType = $state<GridType>('gridjs');

    // Data source management
    #dataSourceType = $state<DataSourceType>('json');
    #restConfig = $state<DataSourceConfig | null>(null);
    #qsConfig = $state<QSDataSourceConfig | null>(null);
    #jsonConfig = $state<JsonDataSourceConfig>({ mode: 'inline', json: '[]' });

    // Column and grid configuration
    #columns = $state<ColumnDef[]>([]);
    #gridConfig = $state<GridConfig>({
        pagination: false,
        pageSize: 25,
        sortable: true,
        filterable: false,
        resizable: true,
    });

    // Loaded data
    #tableData = $state<unknown[]>([]);

    constructor(config: TableWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Table',
            icon: config.icon ?? '📊',
        });

        // Initialize from config
        this.#gridType = config.gridType ?? 'gridjs';
        this.#dataSourceType = config.dataSourceType ?? 'json';
        this.#restConfig = config.restConfig ?? null;
        this.#qsConfig = config.qsConfig ?? null;
        this.#jsonConfig = config.jsonConfig ?? { mode: 'inline', json: '[]' };
        this.#columns = config.columns ?? [];
        this.#gridConfig = { ...this.#gridConfig, ...config.gridConfig };

        // Auto-load data if configured
        if (this.#dataSourceType === 'json' && this.#jsonConfig.mode === 'inline' && this.#jsonConfig.json) {
            this.loadData();
        } else if (this.#dataSourceType !== 'json') {
            // For other types, we might want to load too, or wait for explicit trigger
            this.loadData();
        }
    }

    // === Getters ===

    get gridType(): GridType {
        return this.#gridType;
    }

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

    get columns(): ColumnDef[] {
        return this.#columns;
    }

    get gridConfig(): GridConfig {
        return this.#gridConfig;
    }

    get tableData(): unknown[] {
        return this.#tableData;
    }

    // === Configuration Setters ===

    setGridType(type: GridType): void {
        this.#gridType = type;
    }

    setDataSourceType(type: DataSourceType): void {
        this.#dataSourceType = type;
    }

    setRestConfig(config: DataSourceConfig): void {
        this.#restConfig = config;
    }

    setQSConfig(config: QSDataSourceConfig): void {
        this.#qsConfig = config;
    }

    setJsonConfig(config: JsonDataSourceConfig): void {
        this.#jsonConfig = config;
    }

    setColumns(columns: ColumnDef[]): void {
        this.#columns = columns;
    }

    setGridConfig(config: Partial<GridConfig>): void {
        this.#gridConfig = { ...this.#gridConfig, ...config };
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

            // Auto-detect columns if not configured
            if (this.#columns.length === 0 && this.#tableData.length > 0) {
                this.#autoDetectColumns();
            }

            this.onDataLoaded(this.#tableData);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            this.error = message;
            console.error(`[TableWidget:${this.id}] Load error:`, err);
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

    #autoDetectColumns(): void {
        if (this.#tableData.length === 0) return;

        const firstRow = this.#tableData[0] as Record<string, unknown>;
        this.#columns = Object.keys(firstRow).map((key) => ({
            field: key,
            headerName: this.#humanize(key),
            sortable: true,
        }));
    }

    #humanize(key: string): string {
        return key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
    }

    // === Utility for grid adapters ===

    /**
     * Get columns in Grid.js format
     */
    getGridJsColumns(): { id: string; name: string }[] {
        return this.#columns.map((col) => ({
            id: col.field,
            name: col.headerName ?? this.#humanize(col.field),
        }));
    }

    /**
     * Get columns in Tabulator format
     */
    getTabulatorColumns(): { title: string; field: string }[] {
        return this.#columns.map((col) => ({
            title: col.headerName ?? this.#humanize(col.field),
            field: col.field,
        }));
    }

    /**
     * Get effective columns for simple table  
     */
    getEffectiveColumns(): { key: string; label: string }[] {
        return this.#columns.map((col) => ({
            key: col.field,
            label: col.headerName ?? this.#humanize(col.field),
        }));
    }

    /**
     * Get columns in RevoGrid format
     */
    getRevoGridColumns(): { prop: string; name: string }[] {
        return this.#columns.map((col) => ({
            prop: col.field,
            name: col.headerName ?? this.#humanize(col.field),
        }));
    }
}
