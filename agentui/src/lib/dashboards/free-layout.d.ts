import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type { FreeLayoutConfig, FreePosition } from "./types.js";
interface WidgetEntry {
    widget: Widget;
    position: FreePosition;
}
export declare class FreeLayout {
    dashboard: DashboardView;
    config: FreeLayoutConfig;
    widgets: Map<string, WidgetEntry>;
    el: HTMLElement;
    drag: {
        widget: Widget;
        offsetX: number;
        offsetY: number;
        ghost: HTMLElement;
    } | null;
    savedPositions: Record<string, FreePosition> | null;
    constructor(dashboard: DashboardView, config?: Partial<FreeLayoutConfig>);
    addWidget(widget: Widget, position?: Partial<FreePosition>): void;
    removeWidget(widget: Widget): void;
    moveWidget(widget: Widget, newPosition: Partial<FreePosition>): void;
    resizeWidget(widget: Widget, newSize: {
        width: number;
        height: number;
    }): void;
    getWidget(widgetId: string): Widget | undefined;
    getWidgets(): Widget[];
    getPosition(widgetId: string): FreePosition | undefined;
    renderWidget(widget: Widget, position: FreePosition): void;
    constrainPosition(pos: FreePosition): FreePosition;
    beginDrag(widget: Widget, ev: MouseEvent): void;
    handleDragMove(e: MouseEvent, startX: number, startY: number, initialPos: FreePosition, entry: WidgetEntry, widget: Widget): void;
    beginResize(widget: Widget, ev: MouseEvent): void;
    findFreePosition(width: number, height: number): {
        x: number;
        y: number;
    };
    findFreeSpace(width: number, height: number): FreePosition;
    hasOverlap(rect: FreePosition, excludeId?: string): boolean;
    storageKey(): string;
    saveState(): void;
    loadState(): void;
    getSavedPosition(widgetId: string): FreePosition | null;
    reset(): void;
    destroy(): void;
}
export {};
//# sourceMappingURL=free-layout.d.ts.map