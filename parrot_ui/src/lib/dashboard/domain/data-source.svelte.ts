/**
 * DataSource - Reactive data fetching layer for Widgets and DashboardTabs.
 *
 * Features:
 * - Multiple auth strategies (prioritizing jwt-storage)
 * - Data transformation pipeline
 * - Automatic polling
 * - Retry with exponential backoff
 * - Request timeout and cancellation
 * - Caching (optional)
 */

import { resolveAuthHeaders, type AuthStrategy } from './auth-strategies.js';
import type { DataTransformer, TransformContext } from './transformers.js';

// Re-export for convenience
export type { AuthStrategy };

// ============================================================================
// Types
// ============================================================================

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RetryConfig {
    attempts: number;
    delay: number;          // ms
    backoff: 'linear' | 'exponential';
}

export interface CacheConfig {
    ttl: number;            // ms
    key?: string;           // custom cache key
}

export interface DataSourceConfig<T = unknown, R = T> {
    url: string;
    method?: HttpMethod;
    headers?: Record<string, string>;
    body?: BodyInit | object;
    auth?: AuthStrategy;
    transform?: DataTransformer<T, R>;
    pollInterval?: number;  // ms
    timeout?: number;       // ms, default 30000
    cache?: CacheConfig;
    retry?: RetryConfig;
}

export interface FetchOverrides {
    body?: BodyInit | object;
    params?: Record<string, string>;
    headers?: Record<string, string>;
}

export class DataSourceError extends Error {
    constructor(
        message: string,
        public readonly status?: number,
        public readonly response?: Response,
        public readonly cause?: unknown,
    ) {
        super(message);
        this.name = 'DataSourceError';
    }
}

// ============================================================================
// Cache
// ============================================================================

interface CacheEntry<R> {
    data: R;
    expiresAt: number;
}

const dataSourceCache = new Map<string, CacheEntry<unknown>>();

// ============================================================================
// DataSource Class
// ============================================================================

export class DataSource<T = unknown, R = T> {
    readonly config: DataSourceConfig<T, R>;

    // === Reactive State (Svelte 5) ===
    data = $state<R | null>(null);
    loading = $state(false);
    error = $state<DataSourceError | null>(null);
    lastFetched = $state<Date | null>(null);

    // Internal
    #abortController: AbortController | null = null;
    #pollTimer: ReturnType<typeof setInterval> | null = null;
    #cacheKey: string;

    constructor(config: DataSourceConfig<T, R>) {
        this.config = config;
        this.#cacheKey = config.cache?.key ?? config.url;
    }

    // ========================================================================
    // Public API
    // ========================================================================

    /**
     * Fetch data from the configured URL.
     */
    async fetch(overrides?: FetchOverrides): Promise<R> {
        // Check cache first
        if (this.config.cache) {
            const cached = dataSourceCache.get(this.#cacheKey) as CacheEntry<R> | undefined;
            if (cached && cached.expiresAt > Date.now()) {
                this.data = cached.data;
                this.lastFetched = new Date(cached.expiresAt - this.config.cache.ttl);
                return cached.data;
            }
        }

        // Cancel any in-flight request
        this.cancel();

        this.loading = true;
        this.error = null;
        this.#abortController = new AbortController();

        const timeout = this.config.timeout ?? 30000;
        const timeoutId = setTimeout(() => this.#abortController?.abort(), timeout);

        try {
            const result = await this.#fetchWithRetry(overrides);
            this.data = result;
            this.lastFetched = new Date();
            this.error = null;

            // Update cache
            if (this.config.cache) {
                dataSourceCache.set(this.#cacheKey, {
                    data: result,
                    expiresAt: Date.now() + this.config.cache.ttl,
                });
            }

            return result;
        } catch (err) {
            const error = err instanceof DataSourceError
                ? err
                : new DataSourceError(
                    err instanceof Error ? err.message : String(err),
                    undefined,
                    undefined,
                    err,
                );
            this.error = error;
            throw error;
        } finally {
            clearTimeout(timeoutId);
            this.loading = false;
            this.#abortController = null;
        }
    }

    /**
     * Start polling at the configured interval (or override).
     */
    startPolling(intervalMs?: number): void {
        this.stopPolling();

        const interval = intervalMs ?? this.config.pollInterval;
        if (!interval || interval <= 0) {
            console.warn('[DataSource] No pollInterval configured');
            return;
        }

        // Initial fetch
        this.fetch().catch(() => {
            // Error already stored in state
        });

        this.#pollTimer = setInterval(() => {
            this.fetch().catch(() => {
                // Error already stored in state
            });
        }, interval);
    }

    /**
     * Stop polling.
     */
    stopPolling(): void {
        if (this.#pollTimer) {
            clearInterval(this.#pollTimer);
            this.#pollTimer = null;
        }
    }

    /**
     * Cancel any in-flight requests.
     */
    cancel(): void {
        if (this.#abortController) {
            this.#abortController.abort();
            this.#abortController = null;
        }
    }

    /**
     * Reset state to initial values.
     */
    reset(): void {
        this.cancel();
        this.stopPolling();
        this.data = null;
        this.loading = false;
        this.error = null;
        this.lastFetched = null;
    }

    /**
     * Invalidate cached data.
     */
    invalidateCache(): void {
        dataSourceCache.delete(this.#cacheKey);
    }

    /**
     * Check if DataSource is currently polling.
     */
    get isPolling(): boolean {
        return this.#pollTimer !== null;
    }

    // ========================================================================
    // Private
    // ========================================================================

    async #fetchWithRetry(overrides?: FetchOverrides): Promise<R> {
        const retryConfig = this.config.retry ?? { attempts: 1, delay: 0, backoff: 'linear' };
        let lastError: unknown;

        for (let attempt = 0; attempt < retryConfig.attempts; attempt++) {
            try {
                return await this.#doFetch(overrides);
            } catch (err) {
                lastError = err;

                // Don't retry on abort
                if (err instanceof Error && err.name === 'AbortError') {
                    throw new DataSourceError('Request aborted', undefined, undefined, err);
                }

                // Don't retry on 4xx errors (client errors)
                if (err instanceof DataSourceError && err.status && err.status >= 400 && err.status < 500) {
                    throw err;
                }

                // Calculate delay for next attempt
                if (attempt < retryConfig.attempts - 1) {
                    const delay = retryConfig.backoff === 'exponential'
                        ? retryConfig.delay * Math.pow(2, attempt)
                        : retryConfig.delay;

                    await new Promise(resolve => setTimeout(resolve, delay));
                }
            }
        }

        throw lastError;
    }

    async #doFetch(overrides?: FetchOverrides): Promise<R> {
        // Build URL with params
        let url = this.config.url;
        if (overrides?.params) {
            const params = new URLSearchParams(overrides.params);
            url += (url.includes('?') ? '&' : '?') + params.toString();
        }

        // Resolve auth headers
        const authHeaders = this.config.auth
            ? await resolveAuthHeaders(this.config.auth)
            : {};

        // Merge headers
        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            ...this.config.headers,
            ...authHeaders,
            ...overrides?.headers,
        };

        // Build body
        let body: BodyInit | undefined;
        const rawBody = overrides?.body ?? this.config.body;
        if (rawBody) {
            body = typeof rawBody === 'object' && !(rawBody instanceof FormData) && !(rawBody instanceof Blob)
                ? JSON.stringify(rawBody)
                : rawBody as BodyInit;
        }

        // Execute fetch
        const response = await fetch(url, {
            method: this.config.method ?? 'GET',
            headers,
            body,
            signal: this.#abortController?.signal,
        });

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new DataSourceError(
                `HTTP ${response.status}: ${response.statusText}${text ? ` - ${text}` : ''}`,
                response.status,
                response,
            );
        }

        // Parse response
        const contentType = response.headers.get('Content-Type') ?? '';
        let rawData: T;

        if (contentType.includes('application/json')) {
            rawData = await response.json();
        } else if (contentType.includes('text/')) {
            rawData = await response.text() as T;
        } else {
            rawData = await response.blob() as T;
        }

        // Transform data
        if (this.config.transform) {
            const context: TransformContext = {
                response,
                config: this.config,
                fetchedAt: new Date(),
            };
            return this.config.transform(rawData, context);
        }

        return rawData as unknown as R;
    }
}
