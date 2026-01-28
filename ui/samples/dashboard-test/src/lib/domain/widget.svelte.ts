import type { DashboardTab } from './dashboard-tab.svelte.js';
import type { WidgetMode, ToolbarButton, ConfigTab } from './types.js';

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

    // === Lifecycle ===
    attach(tab: DashboardTab, placement: unknown): void {
        this.#tab = tab;
        this.#placement = placement;
        this.#lastDocked = { tab, placement };
        this.mode = 'docked';
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

    destroy(): void {
        this.detach();
    }
}
