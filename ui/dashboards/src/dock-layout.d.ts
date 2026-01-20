import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type { DockLayoutConfig, DockPosition, PaneLayoutTemplate } from "./types.js";
export declare class DockLayout {
    readonly dashboard: DashboardView;
    readonly config: DockLayoutConfig;
    readonly el: HTMLElement;
    private panes;
    private widgets;
    private currentTemplate;
    private drag;
    private disposers;
    constructor(dashboard: DashboardView, config?: Partial<DockLayoutConfig>);
    applyTemplate(template: PaneLayoutTemplate): void;
    private buildStructure;
    private createPane;
    private createGutter;
    private beginGutterResize;
    splitPane(paneId: string, direction: "horizontal" | "vertical"): void;
    removePane(paneId: string): void;
    addWidget(widget: Widget, placement?: {
        dockPosition?: DockPosition;
        paneId?: string;
    } | string): void;
    private addWidgetToPane;
    removeWidget(widget: Widget): void;
    getWidget(widgetId: string): Widget | undefined;
    getWidgets(): Widget[];
    getPlacement(widgetId: string): {
        dockPosition: DockPosition;
        paneId?: string;
    } | null;
    findFreeSpace(): {
        dockPosition: DockPosition;
    };
    private renderPaneTabs;
    private renderPaneContent;
    private setupPaneDropTarget;
    beginDrag(widget: Widget, ev: PointerEvent): void;
    private endDrag;
    beginResize(widget: Widget, ev: PointerEvent): void;
    getAvailableTemplates(): PaneLayoutTemplate[];
    getCurrentTemplate(): PaneLayoutTemplate | null;
    private storageKey;
    saveState(): void;
    loadState(): void;
    getSavedState(widgetId: string): {
        paneId: string;
        tabIndex: number;
    } | null;
    clearSavedState(): void;
    reset(): void;
    destroy(): void;
}
//# sourceMappingURL=dock-layout.d.ts.map