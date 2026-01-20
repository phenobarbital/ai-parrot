// fetchable.ts - Interface for widgets that fetch data from APIs
import type { Widget } from "./widget.js";

/**
 * Interface for widgets that fetch data from remote APIs.
 */
export interface IFetchable {
    /** Fetch data from the configured URL */
    fetchData(): Promise<void>;

    /** Get the last fetched data */
    getData<T = unknown>(): T | null;

    /** Get the last error if fetch failed */
    getError(): Error | null;

    /** Check if currently fetching */
    isFetching(): boolean;
}

/**
 * Fetch configuration options
 */
export interface FetchConfig {
    /** HTTP method (default: GET) */
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

    /** Request headers */
    headers?: Record<string, string>;

    /** Request body for POST/PUT/PATCH */
    body?: string | object;

    /** Request timeout in milliseconds (default: 30000) */
    timeout?: number;

    /** Auto-refresh interval in milliseconds (0 = disabled) */
    autoRefreshInterval?: number;

    /** Transform the response data before storing */
    transformResponse?: (data: unknown) => unknown;
}

/**
 * Type guard to check if a widget implements IFetchable
 */
export function isFetchable(widget: Widget): widget is Widget & IFetchable {
    return (
        typeof (widget as any).fetchData === "function" &&
        typeof (widget as any).getData === "function" &&
        typeof (widget as any).getError === "function" &&
        typeof (widget as any).isFetching === "function"
    );
}
