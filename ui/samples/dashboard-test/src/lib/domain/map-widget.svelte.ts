/**
 * MapWidget - Widget that displays Leaflet maps with marker data.
 * Supports REST, QuerySource, and JSON data sources.
 */

import { Widget, type WidgetConfig } from './widget.svelte.js';
import { DataSource, type DataSourceConfig } from './data-source.svelte.js';
import { QSDataSource, type QSDataSourceConfig } from './qs-datasource.svelte.js';

// ============================================================================
// Types
// ============================================================================

export type MapDataSourceType = 'rest' | 'qs' | 'json';

export interface MapJsonDataSourceConfig {
    mode: 'inline' | 'url';
    json?: string;
    url?: string;
}

export interface MapConfig {
    tileUrl?: string;
    attribution?: string;
    centerLat?: number;
    centerLng?: number;
    zoom?: number;
    markerLatField?: string;
    markerLngField?: string;
    markerLabelField?: string;
}

export interface MapWidgetConfig extends Omit<WidgetConfig, 'dataSource'>, MapConfig {
    dataSourceType?: MapDataSourceType;
    restConfig?: DataSourceConfig;
    qsConfig?: QSDataSourceConfig;
    jsonConfig?: MapJsonDataSourceConfig;
}

// ============================================================================
// MapWidget
// ============================================================================

export class MapWidget extends Widget {
    // Data source management
    #dataSourceType = $state<MapDataSourceType>('json');
    #restConfig = $state<DataSourceConfig | null>(null);
    #qsConfig = $state<QSDataSourceConfig | null>(null);
    #jsonConfig = $state<MapJsonDataSourceConfig>({ mode: 'inline', json: '[]' });

    // Map configuration
    #tileUrl = $state<string>('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png');
    #attribution = $state<string>('© OpenStreetMap contributors');
    #centerLat = $state<number>(20);
    #centerLng = $state<number>(0);
    #zoom = $state<number>(2);
    #markerLatField = $state<string>('lat');
    #markerLngField = $state<string>('lng');
    #markerLabelField = $state<string>('label');

    // Loaded data
    #mapData = $state<unknown[]>([]);

    constructor(config: MapWidgetConfig) {
        super({
            ...config,
            title: config.title ?? 'Map',
            icon: config.icon ?? '🗺️',
        });

        this.#dataSourceType = config.dataSourceType ?? 'json';
        this.#restConfig = config.restConfig ?? null;
        this.#qsConfig = config.qsConfig ?? null;
        this.#jsonConfig = config.jsonConfig ?? { mode: 'inline', json: '[]' };

        this.#tileUrl = config.tileUrl ?? this.#tileUrl;
        this.#attribution = config.attribution ?? this.#attribution;
        this.#centerLat = config.centerLat ?? this.#centerLat;
        this.#centerLng = config.centerLng ?? this.#centerLng;
        this.#zoom = config.zoom ?? this.#zoom;
        this.#markerLatField = config.markerLatField ?? this.#markerLatField;
        this.#markerLngField = config.markerLngField ?? this.#markerLngField;
        this.#markerLabelField = config.markerLabelField ?? this.#markerLabelField;
    }

    // === Getters ===

    get dataSourceType(): MapDataSourceType {
        return this.#dataSourceType;
    }

    get restConfig(): DataSourceConfig | null {
        return this.#restConfig;
    }

    get qsConfig(): QSDataSourceConfig | null {
        return this.#qsConfig;
    }

    get jsonConfig(): MapJsonDataSourceConfig {
        return this.#jsonConfig;
    }

    get tileUrl(): string {
        return this.#tileUrl;
    }

    get attribution(): string {
        return this.#attribution;
    }

    get centerLat(): number {
        return this.#centerLat;
    }

    get centerLng(): number {
        return this.#centerLng;
    }

    get zoom(): number {
        return this.#zoom;
    }

    get markerLatField(): string {
        return this.#markerLatField;
    }

    get markerLngField(): string {
        return this.#markerLngField;
    }

    get markerLabelField(): string {
        return this.#markerLabelField;
    }

    get mapData(): unknown[] {
        return this.#mapData;
    }

    // === Configuration Setters ===

    setDataSourceType(type: MapDataSourceType): void {
        this.#dataSourceType = type;
    }

    setRestConfig(config: DataSourceConfig): void {
        this.#restConfig = config;
    }

    setQSConfig(config: QSDataSourceConfig): void {
        this.#qsConfig = config;
    }

    setJsonConfig(config: MapJsonDataSourceConfig): void {
        this.#jsonConfig = config;
    }

    setMapConfig(config: MapConfig): void {
        if (config.tileUrl !== undefined) this.#tileUrl = config.tileUrl;
        if (config.attribution !== undefined) this.#attribution = config.attribution;
        if (config.centerLat !== undefined) this.#centerLat = config.centerLat;
        if (config.centerLng !== undefined) this.#centerLng = config.centerLng;
        if (config.zoom !== undefined) this.#zoom = config.zoom;
        if (config.markerLatField !== undefined) this.#markerLatField = config.markerLatField;
        if (config.markerLngField !== undefined) this.#markerLngField = config.markerLngField;
        if (config.markerLabelField !== undefined) this.#markerLabelField = config.markerLabelField;
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

            this.#mapData = Array.isArray(data) ? data : [];
            this.onDataLoaded(this.#mapData);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            this.error = message;
            console.error(`[MapWidget:${this.id}] Load error:`, err);
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
}
