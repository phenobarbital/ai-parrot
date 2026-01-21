import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";
import type { IFetchable, FetchConfig } from "./fetchable.js";
import type { ConfigTab } from "./widget-config-modal.js";
export interface ApiWidgetOptions extends UrlWidgetOptions {
    /** Fetch configuration */
    fetchConfig?: FetchConfig;
    /** Render the fetched data into HTML */
    renderData?: (data: unknown, container: HTMLElement) => void;
}
/**
 * Widget that fetches data from a REST API and displays it.
 * Implements IFetchable interface.
 */
export declare class ApiWidget extends UrlWidget implements IFetchable {
    private _container;
    private _data;
    private _error;
    private _fetching;
    private _fetchConfig;
    private _renderData;
    private _autoRefreshTimer;
    constructor(opts: ApiWidgetOptions);
    private initializeApiWidget;
    protected onInit(): void;
    protected onDestroy(): void;
    fetchData(): Promise<void>;
    getData<T = unknown>(): T | null;
    getError(): Error | null;
    isFetching(): boolean;
    /**
     * Manually set data for the widget without fetching.
     */
    setData(data: unknown): void;
    private renderLoading;
    private renderError;
    protected renderPlaceholder(message: string): void;
    protected renderData(): void;
    protected updateContent(): void;
    private setupAutoRefresh;
    private clearAutoRefresh;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createApiConfigTab;
}
//# sourceMappingURL=api-widget.d.ts.map