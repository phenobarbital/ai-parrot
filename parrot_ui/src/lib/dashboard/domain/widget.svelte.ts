import type { DashboardTab } from './dashboard-tab.svelte.js';
import type { WidgetMode, ToolbarButton, ConfigTab } from './types.js';
import { DataSource, DataSourceError, type DataSourceConfig, type FetchOverrides } from './data-source.svelte.js';

export interface WidgetConfig {
    id?: string;
    title: string;
    icon?: string;

    // Appearance
    titleColor?: string;
    titleBackground?: string;

    // Behavior flags
    closable?: boolean;
    minimizable?: boolean;
    maximizable?: boolean;
    floatable?: boolean;
    resizable?: boolean;
    draggable?: boolean;
    // Chrome
    chromeHidden?: boolean;
    translucent?: boolean;

    // Content areas
    headerContent?: string;
    footerContent?: string;

    // Custom extensions
    toolbar?: ToolbarButton[];

    // Callbacks
    onRefresh?: (widget: Widget) => Promise<void>;
    onClose?: (widget: Widget) => void;

    // DataSource configuration
    dataSource?: DataSourceConfig;
    autoLoad?: boolean;  // default: true if dataSource is set
}

export class Widget {
    readonly id: string;
    readonly config: WidgetConfig;

    // === Reactive State ===
    title = $state<string>('');
    icon = $state<string>('📦');

    // Appearance
    titleColor = $state<string>('#202124');
    titleBackground = $state<string>('#f8f9fa');

    // Behavior flags
    closable = $state(true);
    minimizable = $state(true);
    maximizable = $state(true);
    floatable = $state(true);
    resizable = $state(true);
    draggable = $state(true);
    chromeHidden = $state(false);
    translucent = $state(false);

    // Display mode
    mode = $state<WidgetMode>('docked');
    minimized = $state(false);

    // Content areas
    headerContent = $state<string | null>(null);
    footerContent = $state<string | null>(null);
    statusMessage = $state<string>('');

    // Loading/error state
    loading = $state(false);
    error = $state<string | null>(null);

    // Reference to parent tab (null if floating)
    #tab = $state<DashboardTab | null>(null);
    #placement = $state<unknown>(null);
    #lastDocked: { tab: DashboardTab; placement: unknown } | null = null;
    #floatingStyles = $state<{ left: string; top: string; width: string; height: string } | null>(null);

    // Extensibility
    #customToolbarButtons: ToolbarButton[] = [];
    #customConfigTabs: ConfigTab[] = [];

    // Content injection - resolved in component
    contentRenderer: (() => unknown) | null = null;

    // DataSource integration
    #dataSource: DataSource | null = null;
    #autoLoad: boolean;

    constructor(config: WidgetConfig) {
        this.id = config.id ?? crypto.randomUUID();
        this.config = config;

        // Initialize from config
        this.title = config.title;
        this.icon = config.icon ?? '📦';
        this.titleColor = config.titleColor ?? '#202124';
        this.titleBackground = config.titleBackground ?? '#f8f9fa';
        this.closable = config.closable ?? true;
        this.minimizable = config.minimizable ?? true;
        this.maximizable = config.maximizable ?? true;
        this.floatable = config.floatable ?? true;
        this.resizable = config.resizable ?? true;
        this.draggable = config.draggable ?? true;
        this.chromeHidden = config.chromeHidden ?? false;
        this.translucent = config.translucent ?? false;
        this.headerContent = config.headerContent ?? null;
        this.footerContent = config.footerContent ?? null;

        // DataSource initialization
        this.#autoLoad = config.autoLoad ?? (config.dataSource !== undefined);
        if (config.dataSource) {
            this.#dataSource = new DataSource(config.dataSource);
            this.#registerDataSourceToolbar();
        }
    }

    // === Getters ===
    get tab(): DashboardTab | null {
        return this.#tab;
    }

    get placement(): unknown {
        return this.#placement;
    }

    get isAttached(): boolean {
        return this.#tab !== null;
    }

    get isFloating(): boolean {
        return this.mode === 'floating';
    }

    get isMaximized(): boolean {
        return this.mode === 'maximized';
    }

    get isDocked(): boolean {
        return this.mode === 'docked';
    }

    // === DataSource Getters ===
    get hasDataSource(): boolean {
        return this.#dataSource !== null;
    }

    get data(): unknown | null {
        return this.#dataSource?.data ?? null;
    }

    get dataError(): DataSourceError | null {
        return this.#dataSource?.error ?? null;
    }

    get dataLoading(): boolean {
        return this.#dataSource?.loading ?? false;
    }

    get lastFetched(): Date | null {
        return this.#dataSource?.lastFetched ?? null;
    }

    get isPolling(): boolean {
        return this.#dataSource?.isPolling ?? false;
    }

    // === Lifecycle ===
    attach(tab: DashboardTab, placement: unknown): void {
        this.#tab = tab;
        this.#placement = placement;
        this.#lastDocked = { tab, placement };
        this.mode = 'docked';

        // Auto-load data on attach if configured
        if (this.#autoLoad && this.#dataSource) {
            this.load().catch(err => {
                console.warn(`[Widget:${this.id}] Auto-load failed:`, err);
            });
        }
    }

    detach(): void {
        this.#tab = null;
        this.#placement = null;
    }

    updatePlacement(placement: unknown): void {
        this.#placement = placement;
        if (this.#lastDocked) {
            this.#lastDocked.placement = placement;
        }
    }

    // === Style Setters ===
    setTitleColor(color: string): void {
        this.titleColor = color;
    }

    setTitleBackground(color: string): void {
        this.titleBackground = color;
    }

    /** Darken a hex color by percentage */
    darkenColor(hex: string, percent: number): string {
        hex = hex.replace(/^#/, '');
        let r = parseInt(hex.substring(0, 2), 16);
        let g = parseInt(hex.substring(2, 4), 16);
        let b = parseInt(hex.substring(4, 6), 16);
        r = Math.max(0, Math.floor(r * (1 - percent / 100)));
        g = Math.max(0, Math.floor(g * (1 - percent / 100)));
        b = Math.max(0, Math.floor(b * (1 - percent / 100)));
        return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
    }

    /** Get gradient for titlebar */
    getTitleBarGradient(): string {
        return `linear-gradient(to bottom, ${this.titleBackground}, ${this.darkenColor(this.titleBackground, 15)})`;
    }

    // === Actions ===
    toggleMinimize(): void {
        this.minimized = !this.minimized;
    }

    float(): void {
        if (this.isFloating) return;

        // If maximized, restore first
        if (this.isMaximized) {
            this.restore();
        }

        // Save current position for later re-docking
        if (this.#tab && this.#placement) {
            this.#lastDocked = { tab: this.#tab, placement: this.#placement };
        }

        // Initialize default floating styles if none exist
        if (!this.#floatingStyles) {
            this.#floatingStyles = {
                left: '20px',
                top: '20px',
                width: '400px',
                height: '300px'
            };
        }

        this.mode = 'floating';
    }

    dock(): void {
        if (!this.isFloating && !this.isMaximized) return;

        // Return to last docked position
        if (this.#lastDocked) {
            this.#tab = this.#lastDocked.tab;
            this.#placement = this.#lastDocked.placement;
        }

        this.mode = 'docked';
        this.#floatingStyles = null;
    }

    toggleFloating(): void {
        if (this.isFloating) {
            this.dock();
        } else {
            this.float();
        }
    }

    maximize(): void {
        if (this.isMaximized) return;

        // Save current floating styles if floating
        if (this.isFloating && this.#floatingStyles) {
            // Keep floatingStyles for restore
        } else if (this.#tab && this.#placement) {
            this.#lastDocked = { tab: this.#tab, placement: this.#placement };
            this.#floatingStyles = null;
        }

        this.mode = 'maximized';
    }

    restore(): void {
        if (!this.isMaximized) return;

        // Determine restore target
        if (this.#floatingStyles) {
            // Was floating before maximize
            this.mode = 'floating';
        } else if (this.#lastDocked) {
            // Was docked before maximize
            this.mode = 'docked';
            this.#tab = this.#lastDocked.tab;
            this.#placement = this.#lastDocked.placement;
        } else {
            // Fallback to floating
            this.mode = 'floating';
        }
    }

    async refresh(): Promise<void> {
        if (!this.config.onRefresh) return;

        this.loading = true;
        try {
            await this.config.onRefresh(this);
        } finally {
            this.loading = false;
        }
    }

    close(): void {
        this.config.onClose?.(this);

        if (this.#tab) {
            this.#tab.layout.removeWidget(this);
        }

        this.destroy();
    }

    // === Toolbar Extension API ===
    addToolbarButton(btn: ToolbarButton): void {
        this.#customToolbarButtons.push(btn);
    }

    removeToolbarButton(id: string): void {
        const index = this.#customToolbarButtons.findIndex(b => b.id === id);
        if (index !== -1) {
            this.#customToolbarButtons.splice(index, 1);
        }
    }

    getToolbarButtons(): ToolbarButton[] {
        return [
            ...this.#customToolbarButtons,
            ...(this.config.toolbar ?? [])
        ];
    }

    // === Config Tabs Extension API ===
    addConfigTab(tab: ConfigTab): void {
        this.#customConfigTabs.push(tab);
    }

    removeConfigTab(id: string): void {
        const index = this.#customConfigTabs.findIndex(t => t.id === id);
        if (index !== -1) {
            this.#customConfigTabs.splice(index, 1);
        }
    }

    getConfigTabs(): ConfigTab[] {
        return [...this.#customConfigTabs];
    }

    // === Config Save Hook ===
    onConfigSave(config: Record<string, unknown>): void {
        if (typeof config.title === 'string') this.title = config.title;
        if (typeof config.icon === 'string') this.icon = config.icon;
        if (typeof config.closable === 'boolean') this.closable = config.closable;
        if (typeof config.chromeHidden === 'boolean') this.chromeHidden = config.chromeHidden;
        if (typeof config.translucent === 'boolean') this.translucent = config.translucent;

        const style = config.style as Record<string, string> | undefined;
        if (style) {
            if (typeof style.titleColor === 'string') this.setTitleColor(style.titleColor);
            if (typeof style.titleBackground === 'string') this.setTitleBackground(style.titleBackground);
        }
    }

    // === Utility ===
    setLoading(loading: boolean): void {
        this.loading = loading;
    }

    setError(error: string | null): void {
        this.error = error;
    }

    setStatusMessage(message: string): void {
        this.statusMessage = message;
    }

    setFloatingStyles(styles: { left: string; top: string; width: string; height: string }): void {
        this.#floatingStyles = styles;
    }

    getFloatingStyles(): { left: string; top: string; width: string; height: string } | null {
        return this.#floatingStyles;
    }

    // === DataSource API ===

    /**
     * Load data from the configured DataSource.
     */
    async load(overrides?: FetchOverrides): Promise<unknown> {
        if (!this.#dataSource) {
            throw new Error(`Widget "${this.id}" has no dataSource configured`);
        }

        try {
            const result = await this.#dataSource.fetch(overrides);
            this.onDataLoaded(result);
            return result;
        } catch (err: unknown) {
            const error = err instanceof DataSourceError ? err : new DataSourceError(String(err));
            this.onLoadError(error);
            throw error;
        }
    }

    /**
     * Reload data (alias for load without overrides).
     */
    async reload(): Promise<unknown> {
        return this.load();
    }

    /**
     * Start polling at the configured interval.
     */
    startPolling(intervalMs?: number): void {
        this.#dataSource?.startPolling(intervalMs);
    }

    /**
     * Stop polling.
     */
    stopPolling(): void {
        this.#dataSource?.stopPolling();
    }

    /**
     * Cancel any in-flight data requests.
     */
    cancelLoad(): void {
        this.#dataSource?.cancel();
    }

    /**
     * Clear loaded data.
     */
    clearData(): void {
        this.#dataSource?.reset();
    }

    /**
     * Configure or reconfigure the DataSource.
     */
    setDataSource(config: DataSourceConfig): void {
        this.#dataSource?.reset();
        this.#dataSource = new DataSource(config);
        this.#registerDataSourceToolbar();
    }

    // === DataSource Hooks (override in subclass) ===

    /**
     * Called when data is successfully loaded.
     * Override in subclass to handle data.
     */
    onDataLoaded(data: unknown): void {
        // Default no-op, override in subclass
        void data;
    }

    /**
     * Called when data loading fails.
     * Override in subclass to handle errors.
     */
    onLoadError(error: DataSourceError): void {
        // Default: set error state
        this.error = error.message;
    }

    // === Private DataSource Helpers ===

    #registerDataSourceToolbar(): void {
        // Remove existing if re-registering
        this.removeToolbarButton('ds-reload');

        this.addToolbarButton({
            id: 'ds-reload',
            icon: '↻',
            title: 'Reload Data',
            onClick: () => {
                this.reload().catch((err: unknown) => {
                    console.error(`[Widget:${this.id}] Reload failed:`, err);
                });
            },
            visible: () => this.hasDataSource,
        });
    }

    // === Serialization ===
    toJSON(): WidgetConfig {
        return {
            id: this.id,
            title: this.title,
            icon: this.icon,
            titleColor: this.titleColor,
            titleBackground: this.titleBackground,
            closable: this.closable,
            minimizable: this.minimizable,
            maximizable: this.maximizable,
            floatable: this.floatable,
            resizable: this.resizable,
            draggable: this.draggable,
            chromeHidden: this.chromeHidden,
            translucent: this.translucent,
            headerContent: this.headerContent ?? undefined,
            footerContent: this.footerContent ?? undefined,
            dataSource: this.#dataSource?.config,
            autoLoad: this.#autoLoad,
            // Custom config handling might be needed depending on widget type
            // specific properties (e.g. content for HtmlWidget) should be handled by subclasses overriding toJSON
            // But for now, we'll try to implement a generic one or rely on subclasses if they existed purely as data.
            // Since subclasses like HtmlWidget store state in properties, we might need to genericize this or add a `getConfig()` method.
        };
    }

    destroy(): void {
        this.#dataSource?.reset();
        this.detach();
    }
}

