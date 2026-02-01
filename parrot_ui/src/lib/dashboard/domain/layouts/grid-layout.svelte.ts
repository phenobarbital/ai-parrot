import { LayoutBase } from './layout-base.svelte.js';
import type { Widget } from '../widget.svelte.js';
import type { DashboardTab } from '../dashboard-tab.svelte.js';

import { storageSync as storage } from '../persistence.js';

export interface GridPlacement {
    row: number;
    col: number;
    rowSpan: number;
    colSpan: number;
}

export interface GridConfig {
    cols: number;
    rows: number;
    gap: number;
    minCellSpan: number;
}

export class GridLayout extends LayoutBase {
    // Reactive configuration
    config = $state<GridConfig>({
        cols: 12,
        rows: 12,
        gap: 8,
        minCellSpan: 2
    });

    // Placements map
    #placements = $state<Map<string, GridPlacement>>(new Map());

    // UI Drag state
    dragState = $state<{
        active: boolean;
        widgetId: string | null;
        preview: GridPlacement | null;
        swapTarget: string | null;  // Widget ID to swap with
        resizeMode: boolean;        // Distinguish between move and resize
    }>({ active: false, widgetId: null, preview: null, swapTarget: null, resizeMode: false });

    /**
     * Helper to clone map for reactivity
     */
    #triggerUpdate() {
        this.#placements = new Map(this.#placements);
    }

    constructor(tab: DashboardTab, config?: Partial<GridConfig>) {
        super(tab);
        if (config) {
            this.config = { ...this.config, ...config };
        }
        this.loadState();
    }

    // Derived getters
    get placements(): Map<string, GridPlacement> {
        return this.#placements;
    }

    getPlacement(widgetId: string): GridPlacement | undefined {
        return this.#placements.get(widgetId);
    }

    // Dynamic Grid Expansion
    ensureRows(targetRow: number): void {
        const needed = targetRow + 1;
        if (needed > this.config.rows) {
            console.log('[Grid] Expanding rows to', needed);
            this.config = { ...this.config, rows: needed };
            // saveState call can happen after the operation completes
        }
    }

    // Domain operations
    addWidget(widget: Widget, placement?: Partial<GridPlacement>): void {
        const normalized = this.#normalizePlacement(placement ?? {});

        // Ensure grid is big enough for initial placement check
        this.ensureRows(normalized.row + normalized.rowSpan - 1);

        const resolved = this.#resolveCollisions(widget.id, normalized);

        // Ensure grid is big enough for resolved placement
        this.ensureRows(resolved.row + resolved.rowSpan - 1);

        this.widgets.set(widget.id, widget);
        this.widgets = new Map(this.widgets); // Force reactivity
        this.#placements.set(widget.id, resolved);

        widget.attach(this.tab, resolved);

        this.#placements = new Map(this.#placements); // Force reactivity
        this.saveState();
    }

    removeWidget(widget: Widget): void {
        this.widgets.delete(widget.id);
        this.#placements.delete(widget.id);
        widget.detach();

        this.#placements.delete(widget.id);
        widget.detach();

        this.#triggerUpdate();
        this.saveState();
    }

    moveWidget(widget: Widget, newPlacement: GridPlacement): void {
        console.log('[Grid] moveWidget', widget.id, newPlacement);
        if (!this.widgets.has(widget.id)) {
            console.warn('[Grid] widget not found in map');
            return;
        }

        const normalized = this.#normalizePlacement(newPlacement);
        this.ensureRows(normalized.row + normalized.rowSpan - 1);

        if (this.#canPlace(normalized, widget.id)) {
            console.log('[Grid] Placing widget', widget.id);
            this.#placements.set(widget.id, normalized);
            widget.updatePlacement(normalized);

            this.#placements.set(widget.id, normalized);
            widget.updatePlacement(normalized);

            this.#triggerUpdate();
            this.saveState();
        } else {
            console.warn('[Grid] Cannot place widget at', normalized);
        }
    }

    resizeWidget(widget: Widget, newSpan: { rowSpan: number; colSpan: number }): void {
        const current = this.#placements.get(widget.id);
        if (!current) return;

        const newPlacement = { ...current, ...newSpan };
        this.ensureRows(newPlacement.row + newPlacement.rowSpan - 1);

        this.#placements.set(widget.id, newPlacement);
        widget.updatePlacement(newPlacement);

        this.#triggerUpdate();
        this.saveState();
    }


    // Interactive Resize (called by WidgetRenderer)
    startResize(widgetId: string, handle: string, clientX: number, clientY: number): void {
        const placement = this.#placements.get(widgetId);
        if (!placement) return;

        this.dragState = {
            active: true,
            widgetId,
            preview: placement,
            swapTarget: null,
            resizeMode: true
        };
    }

    updateResize(clientX: number, clientY: number, cellFinder: (x: number, y: number) => { row: number, col: number } | null): void {
        if (!this.dragState.active || !this.dragState.widgetId || !this.dragState.resizeMode) return;

        const cell = cellFinder(clientX, clientY);
        if (!cell) return;

        // Auto-expand during interaction if dragging down
        this.ensureRows(cell.row);

        const original = this.#placements.get(this.dragState.widgetId);
        if (!original) return;

        // Calculate new spans based on bottom-right corner dragging
        // We assume resizing is always from bottom-right (SE) for now as that's the only handle we exposed
        const newColSpan = Math.max(this.config.minCellSpan, cell.col - original.col + 1);
        const newRowSpan = Math.max(this.config.minCellSpan, cell.row - original.row + 1);

        // Update preview
        const newPlacement: GridPlacement = {
            ...original,
            colSpan: Math.min(this.config.cols - original.col, newColSpan),
            // Allow rowSpan to grow indefinitely (bounded by config.rows which we just expanded)
            rowSpan: Math.min(this.config.rows - original.row, newRowSpan)
        };

        this.dragState.preview = newPlacement;
    }

    endResize(): void {
        if (this.dragState.active && this.dragState.widgetId && this.dragState.preview && this.dragState.resizeMode) {
            const widget = this.widgets.get(this.dragState.widgetId);
            if (widget) {
                // Determine span changes
                const newSpan = {
                    colSpan: this.dragState.preview.colSpan,
                    rowSpan: this.dragState.preview.rowSpan
                };
                this.resizeWidget(widget, newSpan);
            }
        }
        this.dragState = { active: false, widgetId: null, preview: null, swapTarget: null, resizeMode: false };
    }

    // Drag & Drop
    startDrag(widgetId: string): void {
        this.dragState = { active: true, widgetId, preview: null, swapTarget: null, resizeMode: false };
    }

    updateDragPreview(placement: GridPlacement): void {
        if (!this.dragState.active || !this.dragState.widgetId) return;

        // Auto expand
        this.ensureRows(placement.row + placement.rowSpan - 1);

        // Check if hovering over another widget
        const targetWidget = this.findWidgetAtCell(placement.row, placement.col);
        if (targetWidget && targetWidget !== this.dragState.widgetId) {
            // Swap mode - show the target widget's placement
            const targetPlacement = this.#placements.get(targetWidget);
            this.dragState.preview = targetPlacement ?? placement;
            this.dragState.swapTarget = targetWidget;
        } else {
            // Normal move mode
            this.dragState.preview = placement;
            this.dragState.swapTarget = null;
        }
    }

    endDrag(): void {
        console.log('[Grid] endDrag', this.dragState);
        if (this.dragState.widgetId && this.dragState.preview) {
            const draggedWidget = this.widgets.get(this.dragState.widgetId);

            if (this.dragState.swapTarget) {
                console.log('[Grid] Swapping', this.dragState.widgetId, this.dragState.swapTarget);
                // Swap widgets
                const targetWidget = this.widgets.get(this.dragState.swapTarget);
                if (draggedWidget && targetWidget) {
                    this.swapWidgets(draggedWidget, targetWidget);
                } else {
                    console.error('[Grid] Swap failed - missing widgets');
                }
            } else if (draggedWidget) {
                console.log('[Grid] Moving', this.dragState.widgetId, this.dragState.preview);
                // Normal move
                this.moveWidget(draggedWidget, this.dragState.preview);
            } else {
                console.error('[Grid] Move failed - missing widget found');
            }
        }
        this.dragState = { active: false, widgetId: null, preview: null, swapTarget: null, resizeMode: false };
    }

    cancelDrag(): void {
        console.log('[Grid] cancelDrag');
        this.dragState = { active: false, widgetId: null, preview: null, swapTarget: null, resizeMode: false };
    }

    // Swap two widgets' positions
    swapWidgets(widgetA: Widget, widgetB: Widget): void {
        const placementA = this.#placements.get(widgetA.id);
        const placementB = this.#placements.get(widgetB.id);

        if (!placementA || !placementB) return;

        // Swap placements
        this.#placements.set(widgetA.id, placementB);
        this.#placements.set(widgetB.id, placementA);

        // Notify widgets
        widgetA.updatePlacement(placementB);
        widgetB.updatePlacement(placementA);

        this.#placements = new Map(this.#placements); // Force reactivity
        this.saveState();
    }

    // Find widget ID at a given cell
    findWidgetAtCell(row: number, col: number): string | null {
        for (const [id, placement] of this.#placements) {
            if (
                row >= placement.row && row < placement.row + placement.rowSpan &&
                col >= placement.col && col < placement.col + placement.colSpan
            ) {
                return id;
            }
        }
        return null;
    }

    // Private Helpers
    #normalizePlacement(p: Partial<GridPlacement>): GridPlacement {
        const { cols, rows, minCellSpan } = this.config;
        return {
            row: Math.max(0, p.row ?? 0), // remove max(rows-1) clamp for row
            col: Math.max(0, Math.min(p.col ?? 0, cols - 1)),
            rowSpan: Math.max(minCellSpan, p.rowSpan ?? 4), // remove max(rows) clamp for rowSpan
            colSpan: Math.max(minCellSpan, Math.min(p.colSpan ?? 4, cols)),
        };
    }

    #canPlace(placement: GridPlacement, excludeId?: string): boolean {
        for (const [id, existing] of this.#placements) {
            if (id === excludeId) continue;
            if (this.#overlaps(placement, existing)) return false;
        }
        return true;
    }

    #overlaps(a: GridPlacement, b: GridPlacement): boolean {
        return !(
            a.col >= b.col + b.colSpan ||
            a.col + a.colSpan <= b.col ||
            a.row >= b.row + b.rowSpan ||
            a.row + a.rowSpan <= b.row
        );
    }

    #resolveCollisions(widgetId: string, placement: GridPlacement): GridPlacement {
        if (this.#canPlace(placement, widgetId)) return placement;

        // Simple collision resolution: find first free space
        // We will only search within current rows + 4 buffer to avoid infinite search
        const { cols, rows } = this.config;
        const searchLimit = rows + 10;

        for (let row = 0; row <= searchLimit; row++) {
            for (let col = 0; col <= cols - placement.colSpan; col++) {
                const candidate = { ...placement, row, col };
                if (this.#canPlace(candidate, widgetId)) return candidate;
            }
        }

        // Fallback: 0,0 default size
        return { row: 0, col: 0, rowSpan: 2, colSpan: 2 };
    }

    findFreeSpace(colSpan: number, rowSpan: number): GridPlacement | null {
        const { cols, rows } = this.config;
        // Search current rows
        for (let row = 0; row <= rows; row++) {
            for (let col = 0; col <= cols - colSpan; col++) {
                const placement = { row, col, rowSpan, colSpan };
                if (this.#canPlace(placement)) return placement;
            }
        }

        // If no space, place at bottom
        const bottomRow = this.getBottomRow();
        return { row: bottomRow, col: 0, rowSpan, colSpan };
    }

    getBottomRow(): number {
        let maxRow = 0;
        for (const p of this.#placements.values()) {
            maxRow = Math.max(maxRow, p.row + p.rowSpan);
        }
        return maxRow;
    }

    // Persistence
    protected override get storageKey(): string {
        return `grid-layout-${this.tab.id}`;
    }

    saveState(): void {
        const state = {
            placements: Object.fromEntries(this.#placements),
            config: this.config
        };
        storage.set(this.storageKey, state);
    }

    loadState(): void {
        const state = storage.get<{
            placements?: Record<string, GridPlacement>;
            config?: GridConfig;
        }>(this.storageKey);

        if (state?.config) {
            this.config = { ...this.config, ...state.config };
        }

        if (state?.placements) {
            this.#placements = new Map(Object.entries(state.placements));
        }
    }

    // === Serialization ===
    serialize(): unknown {
        // GridLayout needs to save the widgets in their specific grid positions if possible.
        // But currently GridLayout seems to just manage a list of widgets and lets the view handle the grid.
        // If we don't store position, we just return the list of widgets.
        // Looking at the code, it seems placement is managed via 'moveWidget' but we need to see how it stores state.
        return this.getWidgets().map(w => w.toJSON());
    }

    reset(): void {
        storage.remove(this.storageKey);
        // Simple reset: auto-arrange
        let col = 0, row = 0;
        const span = 4;
        this.config.rows = 12; // Reset rows to default

        this.#placements.clear();

        for (const [id, widget] of this.widgets) {
            const placement = { row, col, rowSpan: span, colSpan: span };
            this.ensureRows(row + span - 1); // Expand if needed
            this.#placements.set(id, placement);
            widget.updatePlacement(placement);

            col += span;
            if (col >= this.config.cols) {
                col = 0;
                row += span;
            }
        }

        this.#placements = new Map(this.#placements); // Force reactivity
        this.saveState();
    }
}
