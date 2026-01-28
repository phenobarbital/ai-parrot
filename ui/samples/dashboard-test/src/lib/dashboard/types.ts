// types.ts - Tipos e interfaces del sistema de dashboard

export interface Placement {
    row: number;
    col: number;
    rowSpan: number;
    colSpan: number;
}

export interface WidgetState {
    id: string;
    mode: "docked" | "floating" | "maximized";
    minimized: boolean;
    dashboardId: string | null;
    placement: AnyPlacement | null;
    floating?: {
        left: string;
        top: string;
        width: string;
        height: string;
    } | null;
}

export interface DashboardState {
    id: string;
    title: string;
    placements: Record<string, Placement>;
}

export interface DropZone {
    zone: "left" | "right" | "top" | "bottom" | "center" | "swap";
    targetWidget?: string;
    targetPlacement?: Placement;
    previewPlacement: Placement;
    isValid: boolean;
}

export interface DragState {
    widget: import("./widget.js").Widget;
    startX: number;
    startY: number;
    offsetX: number;
    offsetY: number;
    originalPlacement: Placement;
    ghost: HTMLElement;
}

export interface GridConfig {
    cols: number;
    rows: number;
    gap: number;
    minCellSpan: number;
}

export interface WidgetOptions {
    id?: string;
    title: string;
    icon?: string;
    header?: string | HTMLElement;
    content?: string | HTMLElement;
    footer?: string | HTMLElement;
    draggable?: boolean;
    resizable?: boolean;
    closable?: boolean;
    titleColor?: string;
    titleBackground?: string;
    minimizable?: boolean;
    maximizable?: boolean;
    floatable?: boolean;
    /** If true, widget cannot be closed or configured (system widget) */
    is_system?: boolean;
    /** If true, widget has no titlebar, drag from body, no border */
    is_minimal?: boolean;
    toolbar?: ToolbarButton[];
    onRefresh?: (widget: import("./widget.js").Widget) => Promise<void>;
    onClose?: (widget: import("./widget.js").Widget) => void;
}

export interface ToolbarButton {
    id: string;
    title: string;
    icon: string;
    onClick: (widget: import("./widget.js").Widget) => void;
    visible?: (widget: import("./widget.js").Widget) => boolean;
}

export interface DashboardTabConfig {
    id?: string;
    title: string;
    icon?: string;
    closable?: boolean;
}

export interface DashboardTabOptions {
    id?: string;
    grid?: Partial<GridConfig>;
    template?: {
        header?: HTMLElement;
        footer?: HTMLElement;
    };
    layoutMode?: "grid" | "free" | "dock";
    free?: Partial<FreeLayoutConfig>;
    dock?: Partial<DockLayoutConfig>;
}

// === Free Layout Types ===
export interface FreePosition {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface FreeLayoutConfig {
    snapToGrid: boolean;
    gridSize: number;
    padding: number;
}

// === Dock Layout Types ===
export type DockPosition = "left" | "right" | "top" | "bottom" | "center";

export interface DockLayoutConfig {
    minPanelSize: number;
    gutterSize: number;
    initialTemplate?: string; // Template ID to use on init
}

// === Fixed Pane Layout Types ===

/** Structure definition for pane layouts (recursive) */
export type PaneStructure =
    | { type: "row"; children: PaneStructure[]; sizes?: number[] }
    | { type: "column"; children: PaneStructure[]; sizes?: number[] }
    | { type: "pane"; id: string };

/** Layout template definition */
export interface PaneLayoutTemplate {
    id: string;
    name: string;
    icon?: string;
    structure: PaneStructure;
}

/** Runtime pane instance */
export interface Pane {
    id: string;
    el: HTMLElement;
    tabBar: HTMLElement;
    contentArea: HTMLElement;
    widgets: string[]; // Widget IDs
    activeWidget: string | null;
}

export type DockNode = DockLeaf | DockSplit;

export interface DockLeaf {
    type: "leaf";
    widgetId: string;
    el: HTMLElement;
    parent: DockSplit | null;
    originalFlex?: string;
}

export interface DockSplit {
    type: "split";
    direction: "horizontal" | "vertical";
    children: DockNode[];
    sizes: number[];
    el: HTMLElement;
    parent: DockSplit | null;
}

// Extend Placement to support all modes
// Extend Placement to support all modes
export type AnyPlacement = Placement | FreePosition | {
    dockPosition: DockPosition;
    relativeTo?: string; // Widget ID or 'root'
    mode?: "split" | "tab";
};

export interface DashboardEvents {
    // ... existing events
    "widget:added": { widget: import("./widget.js").Widget; dashboard: import("./dashboard.js").DashboardTab; placement: AnyPlacement };
    // ... need to update events.ts too to use AnyPlacement
}