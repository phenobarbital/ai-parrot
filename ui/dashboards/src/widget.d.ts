import { type Dispose } from "./utils.js";
import type { DashboardView } from "./dashboard.js";
import type { WidgetOptions, WidgetState, AnyPlacement } from "./types.js";
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
    getIcon(): string;
    /** Get configuration tabs for this widget. Override in subclasses to add tabs. */
    getConfigTabs(): import("./widget-config-modal.js").ConfigTab[];
    /** Open the settings modal */
    openSettings(): Promise<void>;
    /** Set the widget title */
    setTitle(title: string): void;
    /** Set the widget icon */
    setIcon(icon: string): void;
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