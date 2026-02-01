import type { Widget } from './widget.svelte.js';
import type { DashboardTab } from './dashboard-tab.svelte.js';

export type LayoutMode = 'grid' | 'free' | 'dock' | 'component';

export type DashboardTemplate = 'default' | 'pane-left' | 'pane-right' | 'pane-top' | 'pane-bottom';

// Grid mode presets (Bootstrap-style)
export type GridMode = 'flexible' | 'sidebar-right' | 'sidebar-left' | 'split' | 'three-columns';

export interface GridModeConfig {
    id: GridMode;
    name: string;
    description: string;
    columns: number[];  // Column widths in 12-unit grid
}

export const GRID_MODE_PRESETS: GridModeConfig[] = [
    { id: 'flexible', name: 'Flexible (12×12)', description: 'Standard layout with maximum flexibility', columns: [12] },
    { id: 'sidebar-right', name: 'Sidebar Right (8-4)', description: 'Main content (66%) and sidebar (33%)', columns: [8, 4] },
    { id: 'sidebar-left', name: 'Sidebar Left (4-8)', description: 'Sidebar (33%) and main content (66%)', columns: [4, 8] },
    { id: 'split', name: 'Split (6-6)', description: 'Two equal columns', columns: [6, 6] },
    { id: 'three-columns', name: 'Three Columns (4-4-4)', description: 'Three equal columns', columns: [4, 4, 4] },
];

export interface LayoutEngine {
    readonly tab: DashboardTab;

    // Reactive state accessible
    widgets: Map<string, Widget>;

    // Operations
    addWidget(widget: Widget, placement?: unknown): void;
    removeWidget(widget: Widget): void;
    moveWidget(widget: Widget, placement: unknown): void;

    getWidgets(): Widget[];
    getWidgetIds(): string[];
    getWidget(id: string): Widget | undefined;

    // Persistence
    saveState(): void;
    loadState(): void;
    reset(): void;

    // Explicit Serialization for full save
    serialize(): unknown;

    // Lifecycle
    destroy(): void;
}

// Widget types
export type WidgetMode = 'docked' | 'floating' | 'maximized';

export interface WidgetType {
    id: string;
    name: string;
    description: string;
    icon: string;
}

export interface ToolbarButton {
    id: string;
    icon: string;
    title: string;
    onClick: () => void;
    visible?: () => boolean;
}

export interface ConfigTab {
    id: string;
    label: string;
    icon?: string;
    render: (container: HTMLElement, widget: unknown) => void;
    save: () => Record<string, unknown>;
    onShow?: () => void;
}
