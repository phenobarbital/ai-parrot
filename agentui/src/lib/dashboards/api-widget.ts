// api-widget.ts - Widget that fetches and displays data from REST APIs
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
export class ApiWidget extends UrlWidget implements IFetchable {
    private _container: HTMLElement | undefined;
    private _data: unknown = null;
    private _error: Error | null = null;
    private _fetching: boolean = false;
    private _fetchConfig: FetchConfig;
    private _renderData: ((data: unknown, container: HTMLElement) => void) | undefined;
    private _autoRefreshTimer: number | null = null;

    constructor(opts: ApiWidgetOptions) {
        super({
            icon: "📡",
            ...opts,
            title: opts.title || "API Data",
            onRefresh: async () => this.fetchData(),
        });

        this._fetchConfig = opts.fetchConfig ?? {};
        this._renderData = opts.renderData;

        // Initialize after super
        this.initializeApiWidget();
    }

    private initializeApiWidget(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            overflow: "auto",
            padding: "12px",
            boxSizing: "border-box",
            fontFamily: "system-ui, -apple-system, sans-serif",
            fontSize: "14px",
        });

        this.setContent(this._container);

        // Initial fetch if URL is set
        if (this.url && this.url !== "undefined" && this.url !== "") {
            this.fetchData();
        }

        // Setup auto-refresh
        this.setupAutoRefresh();
    }

    protected override onInit(): void {
        // Do nothing - element is created in constructor after super() returns
    }

    protected override onDestroy(): void {
        this.clearAutoRefresh();
    }

    // === IFetchable Implementation ===

    async fetchData(): Promise<void> {
        if (!this.url || this.url === "undefined" || this.url === "") {
            this.renderPlaceholder("No URL configured");
            return;
        }

        this._fetching = true;
        this._error = null;
        this.renderLoading();

        try {
            const controller = new AbortController();
            const timeout = this._fetchConfig.timeout ?? 30000;
            const timeoutId = setTimeout(() => controller.abort(), timeout);

            const headers: HeadersInit = {
                "Accept": "application/json",
                ...this._fetchConfig.headers,
            };

            let body: string | undefined;
            if (this._fetchConfig.body) {
                if (typeof this._fetchConfig.body === "object") {
                    body = JSON.stringify(this._fetchConfig.body);
                    headers["Content-Type"] = headers["Content-Type"] ?? "application/json";
                } else {
                    body = this._fetchConfig.body;
                }
            }

            const response = await fetch(this.url, {
                method: this._fetchConfig.method ?? "GET",
                headers,
                body: body ?? null,
                signal: controller.signal,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            let data = await response.json();

            // Apply transform if configured
            if (this._fetchConfig.transformResponse) {
                data = this._fetchConfig.transformResponse(data);
            }

            this._data = data;
            console.log("[ApiWidget] Data fetched:", data);
            this.renderData();

        } catch (err) {
            this._error = err instanceof Error ? err : new Error(String(err));
            console.error("[ApiWidget] Fetch error:", this._error);
            this.renderError();
        } finally {
            this._fetching = false;
        }
    }

    getData<T = unknown>(): T | null {
        return this._data as T | null;
    }

    getError(): Error | null {
        return this._error;
    }

    isFetching(): boolean {
        return this._fetching;
    }

    /**
     * Manually set data for the widget without fetching.
     */
    setData(data: unknown): void {
        this._data = data;
        this.renderData();
    }

    // === Rendering ===

    private renderLoading(): void {
        if (!this._container) return;
        this._container.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-muted, #888);">
                <span style="font-size: 24px; animation: spin 1s linear infinite;">⟳</span>
                <span style="margin-left: 8px;">Loading...</span>
            </div>
            <style>
                @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            </style>
        `;
    }

    private renderError(): void {
        if (!this._container) return;
        this._container.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--error, #dc3545);">
                <span style="font-size: 32px;">⚠️</span>
                <span style="margin-top: 8px; font-weight: 500;">Error fetching data</span>
                <span style="margin-top: 4px; font-size: 12px; color: var(--text-muted, #888);">${this._error?.message ?? "Unknown error"}</span>
            </div>
        `;
    }

    protected renderPlaceholder(message: string): void {
        if (!this._container) return;
        this._container.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted, #888);">
                <span style="font-size: 32px;">📡</span>
                <span style="margin-top: 8px;">${message}</span>
            </div>
        `;
    }

    protected renderData(): void {
        if (!this._container) return;

        // Use custom renderer if provided
        if (this._renderData) {
            this._container.innerHTML = "";
            this._renderData(this._data, this._container);
            return;
        }

        // Default: render as formatted JSON
        this._container.innerHTML = `
            <pre style="margin: 0; white-space: pre-wrap; word-break: break-word; font-family: 'Monaco', 'Menlo', monospace; font-size: 12px; line-height: 1.5;">${JSON.stringify(this._data, null, 2)}</pre>
        `;
    }

    protected updateContent(): void {
        // For ApiWidget, updateContent triggers a fetch
        this.fetchData();
    }

    // === Auto-refresh ===

    private setupAutoRefresh(): void {
        this.clearAutoRefresh();

        const interval = this._fetchConfig.autoRefreshInterval;
        if (interval && interval > 0) {
            this._autoRefreshTimer = window.setInterval(() => {
                this.fetchData();
            }, interval);
        }
    }

    private clearAutoRefresh(): void {
        if (this._autoRefreshTimer !== null) {
            clearInterval(this._autoRefreshTimer);
            this._autoRefreshTimer = null;
        }
    }

    // === Config ===

    override getConfigTabs(): ConfigTab[] {
        return [
            ...super.getConfigTabs(),
            this.createApiConfigTab()
        ];
    }

    protected override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);

        if (typeof config.method === "string") {
            const method = config.method as FetchConfig["method"];
            if (method) {
                this._fetchConfig.method = method;
            }
        }
        if (typeof config.timeout === "number") {
            this._fetchConfig.timeout = config.timeout;
        }
        if (typeof config.autoRefreshInterval === "number") {
            this._fetchConfig.autoRefreshInterval = config.autoRefreshInterval;
            this.setupAutoRefresh();
        }
        if (typeof config.headers === "string") {
            try {
                this._fetchConfig.headers = JSON.parse(config.headers);
            } catch { }
        }
    }

    private createApiConfigTab(): ConfigTab {
        let methodSelect: HTMLSelectElement;
        let timeoutInput: HTMLInputElement;
        let autoRefreshInput: HTMLInputElement;
        let headersInput: HTMLTextAreaElement;

        return {
            id: "api",
            label: "API",
            icon: "🔧",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                // Method select
                const methodGroup = document.createElement("div");
                Object.assign(methodGroup.style, { marginBottom: "12px" });

                const methodLabel = document.createElement("label");
                methodLabel.textContent = "HTTP Method";
                Object.assign(methodLabel.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });

                methodSelect = document.createElement("select");
                for (const method of ["GET", "POST", "PUT", "PATCH", "DELETE"]) {
                    const option = document.createElement("option");
                    option.value = method;
                    option.textContent = method;
                    option.selected = (this._fetchConfig.method ?? "GET") === method;
                    methodSelect.appendChild(option);
                }
                Object.assign(methodSelect.style, {
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "14px",
                });

                methodGroup.append(methodLabel, methodSelect);
                container.appendChild(methodGroup);

                // Timeout input
                const timeoutGroup = document.createElement("div");
                Object.assign(timeoutGroup.style, { marginBottom: "12px" });

                const timeoutLabel = document.createElement("label");
                timeoutLabel.textContent = "Timeout (ms)";
                Object.assign(timeoutLabel.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });

                timeoutInput = document.createElement("input");
                timeoutInput.type = "number";
                timeoutInput.min = "1000";
                timeoutInput.value = String(this._fetchConfig.timeout ?? 30000);
                Object.assign(timeoutInput.style, {
                    width: "120px",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "14px",
                });

                timeoutGroup.append(timeoutLabel, timeoutInput);
                container.appendChild(timeoutGroup);

                // Auto-refresh input
                const autoRefreshGroup = document.createElement("div");
                Object.assign(autoRefreshGroup.style, { marginBottom: "12px" });

                const autoRefreshLabel = document.createElement("label");
                autoRefreshLabel.textContent = "Auto-refresh (ms, 0 = disabled)";
                Object.assign(autoRefreshLabel.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });

                autoRefreshInput = document.createElement("input");
                autoRefreshInput.type = "number";
                autoRefreshInput.min = "0";
                autoRefreshInput.step = "1000";
                autoRefreshInput.value = String(this._fetchConfig.autoRefreshInterval ?? 0);
                Object.assign(autoRefreshInput.style, {
                    width: "120px",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "14px",
                });

                autoRefreshGroup.append(autoRefreshLabel, autoRefreshInput);
                container.appendChild(autoRefreshGroup);

                // Headers textarea
                const headersGroup = document.createElement("div");
                Object.assign(headersGroup.style, { marginBottom: "12px" });

                const headersLabel = document.createElement("label");
                headersLabel.textContent = "Headers (JSON)";
                Object.assign(headersLabel.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });

                headersInput = document.createElement("textarea");
                headersInput.value = JSON.stringify(this._fetchConfig.headers ?? {}, null, 2);
                headersInput.placeholder = '{"Authorization": "Bearer ..."}';
                Object.assign(headersInput.style, {
                    width: "100%",
                    height: "80px",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "12px",
                    fontFamily: "monospace",
                    resize: "vertical",
                    boxSizing: "border-box",
                });

                headersGroup.append(headersLabel, headersInput);
                container.appendChild(headersGroup);
            },
            save: () => ({
                method: methodSelect?.value ?? this._fetchConfig.method,
                timeout: parseInt(timeoutInput?.value, 10) || 30000,
                autoRefreshInterval: parseInt(autoRefreshInput?.value, 10) || 0,
                headers: headersInput?.value ?? "{}",
            }),
        };
    }
}
