import type { PaneLayoutTemplate } from "./types.js";
/**
 * 6 Popular Layout Templates
 *
 * Each template defines a fixed pane structure.
 * Widgets can be placed into panes (with tabs if multiple widgets).
 */
/** Single pane (full screen) */
export declare const LAYOUT_SINGLE: PaneLayoutTemplate;
/** Two equal columns */
export declare const LAYOUT_2_COLUMNS: PaneLayoutTemplate;
/** Sidebar left + main area */
export declare const LAYOUT_SIDEBAR_MAIN: PaneLayoutTemplate;
/** Left column + two rows on right */
export declare const LAYOUT_LEFT_2_RIGHT: PaneLayoutTemplate;
/** Three rows on left + one column on right */
export declare const LAYOUT_3_LEFT_1_RIGHT: PaneLayoutTemplate;
/** Main area + bottom panel */
export declare const LAYOUT_MAIN_BOTTOM: PaneLayoutTemplate;
/** All templates */
export declare const DOCK_TEMPLATES: PaneLayoutTemplate[];
/** Get template by ID */
export declare function getTemplate(id: string): PaneLayoutTemplate | undefined;
//# sourceMappingURL=dock-templates.d.ts.map