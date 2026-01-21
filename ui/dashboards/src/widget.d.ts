import { type Dispose } from "./utils.js";
import type { DashboardView } from "./dashboard.js";
import type { WidgetOptions, WidgetState, ToolbarButton, AnyPlacement } from "./types.js";
type WidgetMode = "docked" | "floating" | "maximized";
export declare class Widget {
    readonly id: string;
    readonly el: HTMLElement;
    protected readonly opts: WidgetOptions;
    protected readonly titleBar: HTMLElement;
    protected readonly titleText: HTMLElement;
    protected readonly toolbar: HTMLElement;
    protected readonly burgerBtn: HTMLElement;
    protected readonly headerSection: HTMLElement;
    protected readonly contentSection: HTMLElement;
    protected readonly footerSection: HTMLElement;
    protected readonly resizeHandle: HTMLElement;
    protected dashboard: DashboardView | null;
    protected placement: AnyPlacement | null;
    protected mode: WidgetMode;
    protected minimized: boolean;
    protected lastDocked: {
        dashboard: DashboardView;
        placement: AnyPlacement;
    } | null;
    protected floatingStyles: {
        left: string;
        top: string;
        width: string;
        height: string;
    } | null;
    protected disposers: Dispose[];
    protected stateRestored: boolean;
    protected customToolbarButtons: ToolbarButton[];
    protected customConfigTabs: import("./widget-config-modal.js").ConfigTab[];
    constructor(opts: WidgetOptions);
    /** Called after widget is fully constructed. Override in subclasses. */
    protected onInit(): void;
    /** Called before widget is destroyed. Override in subclasses. */
    protected onDestroy(): void;
    /** Called before refresh starts. Override in subclasses. */
    protected onRefresh(): void;
    /** Called after refresh completes. Override in subclasses. */
    protected onReload(): void;
    /** Called when configuration is saved. Override in subclasses. */
    protected onConfigSave(config: Record<string, unknown>): void;
    getTitle(): string;
    setTitle(title: string): void;
    getIcon(): string;
    setIcon(icon: string): void;
    setTitleColor(color: string): void;
    getTitleColor(): string;
    setTitleBackground(color: string): void;
    /** Helper to darken a hex color by a percentage */
    private darkenColor;
    getTitleBackground(): string;
    isClosable(): boolean;
    /** Get configuration tabs for this widget. Override in subclasses to add tabs. */
    getConfigTabs(): import("./widget-config-modal.js").ConfigTab[];
    /** Open the settings modal */
    openSettings(): Promise<void>;
    /** Add a custom button to the toolbar */
    addToolbarButton(btn: ToolbarButton): void;
    /** Remove a custom toolbar button by ID */
    removeToolbarButton(id: string): void;
    /** Add a custom configuration tab */
    addConfigTab(tab: import("./widget-config-modal.js").ConfigTab): void;
    /** Remove a custom configuration tab by ID */
    removeConfigTab(id: string): void;
    getDashboard(): DashboardView | null;
    getPlacement(): AnyPlacement | null;
    isFloating(): boolean;
    isMaximized(): boolean;
    isDocked(): boolean;
    isMinimized(): boolean;
    setDocked(dashboard: DashboardView, placement: AnyPlacement): void;
    setPlacement(placement: AnyPlacement): void;
    setContent(content: string | HTMLElement): void;
    toggleMinimize(): void;
    float(): void;
    /**
     * DOCK CORREGIDO: Ahora siempre tiene un destino
     */
    dock(): void;
    toggleFloating(): void;
    maximize(): void;
    restore(): void;
    refresh(): Promise<void>;
    close(): void;
    openInNewWindow(): void;
    private setSection;
    private buildToolbar;
    private renderToolbar;
    private getToolbarButtons;
    private setupInteractions;
    private beginFloatingDrag;
    private beginFloatingResize;
    private showBurgerMenu;
    private storageKey;
    saveState(): void;
    getSavedState(): WidgetState | null;
    restoreState(): void;
    destroy(): void;
}
export {};
//# sourceMappingURL=widget.d.ts.map