import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type { Placement, GridConfig } from "./types.js";
export type { Placement };
export interface GridPreset {
    id: string;
    name: string;
    cols: number;
    templateColumns: string;
    description?: string;
}
export declare const LAYOUT_PRESETS: Record<string, GridPreset>;
export declare class GridLayout {
    readonly el: HTMLElement;
    private readonly dashboard;
    private config;
    private currentPreset;
    private readonly widgets;
    private readonly disposers;
    private drag;
    private dropPreview;
    private activeDropZone;
    constructor(dashboard: DashboardView, config?: Partial<GridConfig>);
    private applyGridStyles;
    setPreset(presetId: string): void;
    getCurrentPreset(): string;
    private reflowWidgets;
    addWidget(widget: Widget, placement: Placement): void;
    removeWidget(widget: Widget): void;
    moveWidget(widget: Widget, newPlacement: Placement): void;
    swapWidgets(widgetA: Widget, widgetB: Widget): void;
    getWidget(widgetId: string): Widget | undefined;
    getWidgets(): Widget[];
    getPlacement(widgetId: string): Placement | undefined;
    private renderWidget;
    beginDrag(widget: Widget, ev: PointerEvent): void;
    private handleDragMove;
    private handleDragEnd;
    private cellFromPoint;
    private computeDropZone;
    private calculateAvailableWidth;
    private findWidgetAtCell;
    private canPlace;
    private placementsOverlap;
    private createDropPreview;
    private updateDropPreview;
    private hideDropPreview;
    beginResize(widget: Widget, ev: PointerEvent): void;
    findFreeSpace(colSpan: number, rowSpan: number): Placement | null;
    private normalizePlacement;
    private resolveCollisions;
    private storageKey;
    private saveState;
    private loadState;
    getSavedPlacement(widgetId: string): Placement | null;
    reset(): void;
    destroy(): void;
}
//# sourceMappingURL=grid-layout.d.ts.map