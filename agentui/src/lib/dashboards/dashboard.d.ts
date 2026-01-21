import { FreeLayout } from "./free-layout.js";
import { DockLayout } from "./dock-layout.js";
import { GridLayout } from "./grid-layout.js";
import { Widget } from "./widget.js";
import type { DashboardTabOptions, DashboardViewOptions, AnyPlacement } from "./types.js";
export { GridLayout, FreeLayout, DockLayout };
type LayoutEngine = GridLayout | FreeLayout | DockLayout;
export declare class DashboardView {
    readonly id: string;
    readonly el: HTMLElement;
    readonly header: HTMLElement;
    readonly main: HTMLElement;
    readonly footer: HTMLElement;
    readonly layout: LayoutEngine;
    readonly layoutMode: "grid" | "free" | "dock";
    private title;
    private icon;
    private disposers;
    private slideshowState;
    constructor(id: string, title: string, icon: string, opts: DashboardViewOptions);
    setGridLayout(presetId: string): void;
    getGridLayoutPreset(): string | null;
    getTitle(): string;
    setTitle(title: string): void;
    getIcon(): string;
    setIcon(icon: string): void;
    getLayoutMode(): "grid" | "free" | "dock";
    getWidgets(): Widget[];
    addWidget(widget: Widget, placement: AnyPlacement): void;
    removeWidget(widget: Widget): void;
    enterSlideshow(): void;
    private showSlideshowWidget;
    slideshowNext(): void;
    slideshowPrev(): void;
    exitSlideshow(): void;
    destroy(): void;
    /**
     * Save the current widget layout to localStorage.
     */
    saveLayout(): void;
    /**
     * Reset layout to default positions and clear saved state.
     */
    resetLayout(): void;
    /**
     * Load saved layout from localStorage (called on init).
     */
    loadLayout(): void;
}
export declare class DashboardContainer {
    readonly el: HTMLElement;
    private readonly tabBar;
    private readonly tabStrip;
    private readonly addBtn;
    private readonly content;
    private readonly dashboards;
    private activeId;
    private disposers;
    constructor(mount: HTMLElement);
    private scrollTabs;
    private showDashboardMenu;
    private injectStyles;
    /**
     * Obtener todos los dashboards
     */
    getAllDashboards(): DashboardView[];
    /**
     * Obtener dashboard por ID
     */
    getDashboard(id: string): DashboardView | undefined;
    /**
     * Obtener el dashboard activo
     */
    getActiveDashboard(): DashboardView | undefined;
    /**
     * Obtener todos los widgets de todos los dashboards
     */
    getAllWidgets(): Widget[];
    /**
     * Buscar widget por ID en cualquier dashboard
     */
    findWidget(widgetId: string): {
        widget: Widget;
        dashboard: DashboardView;
    } | null;
    /**
     * Crear un nuevo dashboard vacío
     */
    createDashboard(options?: {
        title?: string;
        icon?: string;
    }): DashboardView;
    /**
     * Añadir dashboard con configuración completa
     */
    addDashboard(tab: DashboardTabOptions, view?: DashboardViewOptions): DashboardView;
    /**
     * Remover dashboard
     */
    removeDashboard(id: string): void;
    /**
     * Activar dashboard por ID
     */
    activate(id: string): void;
    /**
     * Iterar sobre dashboards
     */
    forEach(callback: (dashboard: DashboardView, id: string) => void): void;
    private createTabElement;
    private showTabMenu;
    private openWidgetSelector;
    destroy(): void;
}
//# sourceMappingURL=dashboard.d.ts.map