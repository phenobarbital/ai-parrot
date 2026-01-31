/**
 * QSDataSource - Specialized DataSource for QuerySource API.
 */

import { DataSource, type DataSourceConfig } from './data-source.svelte.js';
import { resolveAuthHeaders } from './auth-strategies.js';

export interface QSDataSourceConfig extends Omit<DataSourceConfig, 'url' | 'method'> {
    slug: string;
    baseUrl?: string;
    payload?: Record<string, unknown>;
    fields?: string[];
    filter?: Record<string, unknown>;
}

export const DEFAULT_QS_URL = 'http://navigator-dev.dev.local:5000';

export class QSDataSource<T = unknown> extends DataSource<T> {
    readonly qsConfig: QSDataSourceConfig;

    constructor(config: QSDataSourceConfig) {
        // Resolve Base URL
        const baseUrl = config.baseUrl
            || (typeof localStorage !== 'undefined' ? localStorage.getItem('qs_api_url') : null)
            || (import.meta.env ? import.meta.env.VITE_QS_API_URL : null)
            || DEFAULT_QS_URL;

        // Construct full URL
        const url = `${baseUrl}/api/v2/services/queries/${config.slug}`;

        // Build Payload
        const payload: Record<string, unknown> = { ...(config.payload ?? {}) };

        if (config.fields && config.fields.length > 0) {
            payload.fields = config.fields;
        }

        if (config.filter && Object.keys(config.filter).length > 0) {
            payload.filter = config.filter;
        }

        // Parent Config
        super({
            ...config,
            url,
            method: 'POST',
            body: payload,
            auth: config.auth ?? { type: 'jwt-storage', storageKey: 'auth_token' }
        });

        this.qsConfig = config;
    }
}
