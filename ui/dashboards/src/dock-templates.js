/**
 * 6 Popular Layout Templates
 *
 * Each template defines a fixed pane structure.
 * Widgets can be placed into panes (with tabs if multiple widgets).
 */
/** Single pane (full screen) */
export const LAYOUT_SINGLE = {
    id: "single",
    name: "Single Pane",
    icon: "□",
    structure: { type: "pane", id: "main" }
};
/** Two equal columns */
export const LAYOUT_2_COLUMNS = {
    id: "2-columns",
    name: "Two Columns",
    icon: "▐▌",
    structure: {
        type: "row",
        children: [
            { type: "pane", id: "left" },
            { type: "pane", id: "right" }
        ],
        sizes: [50, 50]
    }
};
/** Sidebar left + main area */
export const LAYOUT_SIDEBAR_MAIN = {
    id: "sidebar-main",
    name: "Sidebar + Main",
    icon: "▏▇",
    structure: {
        type: "row",
        children: [
            { type: "pane", id: "sidebar" },
            { type: "pane", id: "main" }
        ],
        sizes: [25, 75]
    }
};
/** Left column + two rows on right */
export const LAYOUT_LEFT_2_RIGHT = {
    id: "left-2-right",
    name: "Left + 2 Right Rows",
    icon: "▐▀▄",
    structure: {
        type: "row",
        children: [
            { type: "pane", id: "left" },
            {
                type: "column",
                children: [
                    { type: "pane", id: "top-right" },
                    { type: "pane", id: "bottom-right" }
                ],
                sizes: [50, 50]
            }
        ],
        sizes: [40, 60]
    }
};
/** Three rows on left + one column on right */
export const LAYOUT_3_LEFT_1_RIGHT = {
    id: "3-left-1-right",
    name: "3 Left Rows + Right",
    icon: "▄▄▐",
    structure: {
        type: "row",
        children: [
            {
                type: "column",
                children: [
                    { type: "pane", id: "top-left" },
                    { type: "pane", id: "middle-left" },
                    { type: "pane", id: "bottom-left" }
                ],
                sizes: [33, 34, 33]
            },
            { type: "pane", id: "right" }
        ],
        sizes: [60, 40]
    }
};
/** Main area + bottom panel */
export const LAYOUT_MAIN_BOTTOM = {
    id: "main-bottom",
    name: "Main + Bottom Panel",
    icon: "▀▃",
    structure: {
        type: "column",
        children: [
            { type: "pane", id: "main" },
            { type: "pane", id: "bottom" }
        ],
        sizes: [70, 30]
    }
};
/** All templates */
export const DOCK_TEMPLATES = [
    LAYOUT_SINGLE,
    LAYOUT_2_COLUMNS,
    LAYOUT_SIDEBAR_MAIN,
    LAYOUT_LEFT_2_RIGHT,
    LAYOUT_3_LEFT_1_RIGHT,
    LAYOUT_MAIN_BOTTOM
];
/** Get template by ID */
export function getTemplate(id) {
    return DOCK_TEMPLATES.find(t => t.id === id);
}
//# sourceMappingURL=dock-templates.js.map