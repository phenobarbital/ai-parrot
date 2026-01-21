// grid-layout.ts - Sistema de layout de grilla mejorado
import { clamp, cssPx, el, on, storage, uid } from "./utils.js";
import { bus } from "./events.js";
const DEFAULT_CONFIG = {
    cols: 12,
    rows: 12,
    gap: 8,
    minCellSpan: 2,
};
export const LAYOUT_PRESETS = {
    "standard": {
        id: "standard",
        name: "Flexible (12x12)",
        cols: 12,
        templateColumns: "repeat(12, 1fr)",
        description: "Standard layout with maximum flexibility"
    },
    "sidebar-right": {
        id: "sidebar-right",
        name: "Sidebar Right (8-4)",
        cols: 2,
        templateColumns: "2fr 1fr",
        description: "Main content (66%) and sidebar (33%)"
    },
    "split": {
        id: "split",
        name: "Split (6-6)",
        cols: 2,
        templateColumns: "1fr 1fr",
        description: "Two equal columns"
    },
    "three-col": {
        id: "three-col",
        name: "Three Columns (4-4-4)",
        cols: 3,
        templateColumns: "1fr 1fr 1fr",
        description: "Three equal columns"
    }
};
export class GridLayout {
    el;
    dashboard;
    config;
    currentPreset = "standard";
    widgets = new Map();
    disposers = [];
    // Drag state
    drag = null;
    dropPreview = null;
    activeDropZone = null;
    constructor(dashboard, config = {}) {
        this.dashboard = dashboard;
        this.config = { ...DEFAULT_CONFIG, ...config };
        // Crear elemento de grilla con CSS Grid
        this.el = el("div", { class: "grid-layout" });
        this.applyGridStyles();
        this.loadState();
        // Listen for minimize toggle
        this.disposers.push(bus.on("widget:minimized", ({ widget }) => {
            const entry = this.widgets.get(widget.id);
            if (!entry)
                return;
            if (widget.isMinimized()) {
                // Save original span and collapse to 1 row
                entry.originalRowSpan = entry.placement.rowSpan;
                entry.placement.rowSpan = 1; // Collapse
            }
            else {
                // Restore
                if (entry.originalRowSpan) {
                    entry.placement.rowSpan = entry.originalRowSpan;
                    delete entry.originalRowSpan;
                }
            }
            this.renderWidget(widget, entry.placement);
            this.saveState();
        }));
    }
    applyGridStyles() {
        const { cols, rows, gap } = this.config;
        Object.assign(this.el.style, {
            display: "grid",
            gridTemplateColumns: this.config.templateColumns || `repeat(${cols}, 1fr)`,
            gridTemplateRows: `repeat(${rows}, 1fr)`,
            gap: `${gap}px`,
            height: "100%",
            position: "relative",
            padding: `${gap}px`,
        });
    }
    setPreset(presetId) {
        const preset = LAYOUT_PRESETS[presetId];
        if (!preset)
            return;
        this.currentPreset = presetId;
        this.config = {
            ...this.config,
            cols: preset.cols,
            // Store template columns in config for applyGridStyles
            templateColumns: preset.templateColumns,
            // Reset minCellSpan for stricter layouts if needed, or keep default
            minCellSpan: preset.cols <= 3 ? 1 : 2
        };
        this.applyGridStyles();
        // Relayout all widgets to fit new grid
        this.reflowWidgets();
        this.saveState();
    }
    getCurrentPreset() {
        return this.currentPreset;
    }
    reflowWidgets() {
        // Create a temporary map to hold new positions
        const entries = Array.from(this.widgets.values());
        // Clear grid effectively by resetting placements one by one
        // We'll just re-add everyone using collision resolution against the new grid
        // Sort by row/col to maintain relative order roughly
        entries.sort((a, b) => {
            if (a.placement.row !== b.placement.row)
                return a.placement.row - b.placement.row;
            return a.placement.col - b.placement.col;
        });
        // Clear widgets temporarily (logically, not DOM) to resolve new positions
        const widgetsToPlace = entries.map(e => ({ widget: e.widget, old: e.placement }));
        this.widgets.clear();
        for (const { widget, old } of widgetsToPlace) {
            // Adapt old placement to new grid constraints
            // If new grid has fewer columns, we must clamp
            // For strict layouts (cols <= 3), force colSpan=1 usually
            const isStrict = this.config.cols <= 3;
            let newCol = old.col;
            let newSpan = old.colSpan;
            if (this.currentPreset === "standard") {
                // If returning to 12-col, maybe try to restore original width 
                // if we had saved it? For now, just map back linearly? 
                // Getting back from 2-col to 12-col is hard to guess perfect intent.
                // We'll just let them fall in place.
                // Simple mapping: 
                // If it was col 0 in 2-col (total 2), it's 0-6 in 12-col?
                // That's complex. Let's start simple: standard collision logic.
                newSpan = Math.max(2, Math.min(newSpan, 12));
            }
            else {
                // Moving to strict layout
                // Force single column width per item usually, or full width
                newSpan = 1;
                // Map column: if it was on right half (col > 6 in 12-col), put in col 1 of 2-col
                if (old.col >= 6 && this.config.cols >= 2)
                    newCol = 1;
                else
                    newCol = 0;
            }
            const initialPlace = {
                row: old.row,
                col: newCol,
                colSpan: newSpan,
                rowSpan: old.rowSpan
            };
            // Add using standard logic
            this.addWidget(widget, initialPlace);
        }
    }
    // === Widget Management ===
    addWidget(widget, placement) {
        // Normalizar y validar placement
        const normalized = this.normalizePlacement(placement);
        // Buscar espacio libre si hay colisión
        const final = this.resolveCollisions(widget.id, normalized);
        console.log(`[GridLayout] addWidget: ${widget.id}`, { placement, normalized, final });
        this.widgets.set(widget.id, { widget, placement: final });
        this.renderWidget(widget, final);
        widget.setDocked(this.dashboard, final);
        bus.emit("widget:added", {
            widget,
            dashboard: this.dashboard,
            placement: final
        });
        this.saveState();
    }
    removeWidget(widget) {
        const entry = this.widgets.get(widget.id);
        if (!entry)
            return;
        widget.el.remove();
        this.widgets.delete(widget.id);
        bus.emit("widget:removed", { widget, dashboard: this.dashboard });
        this.saveState();
    }
    moveWidget(widget, newPlacement) {
        const entry = this.widgets.get(widget.id);
        if (!entry)
            return;
        const oldPlacement = { ...entry.placement };
        const normalized = this.normalizePlacement(newPlacement);
        entry.placement = normalized;
        this.renderWidget(widget, normalized);
        widget.setPlacement(normalized);
        bus.emit("widget:moved", { widget, from: oldPlacement, to: normalized });
        this.saveState();
    }
    swapWidgets(widgetA, widgetB) {
        const entryA = this.widgets.get(widgetA.id);
        const entryB = this.widgets.get(widgetB.id);
        if (!entryA || !entryB)
            return;
        const placementA = { ...entryA.placement };
        const placementB = { ...entryB.placement };
        entryA.placement = placementB;
        entryB.placement = placementA;
        this.renderWidget(widgetA, placementB);
        this.renderWidget(widgetB, placementA);
        widgetA.setPlacement(placementB);
        widgetB.setPlacement(placementA);
        this.saveState();
    }
    getWidget(widgetId) {
        return this.widgets.get(widgetId)?.widget;
    }
    getWidgets() {
        return Array.from(this.widgets.values()).map(e => e.widget);
    }
    getPlacement(widgetId) {
        return this.widgets.get(widgetId)?.placement;
    }
    // === Rendering ===
    renderWidget(widget, placement) {
        const { row, col, rowSpan, colSpan } = placement;
        if (!widget.el.parentElement) {
            this.el.appendChild(widget.el);
        }
        Object.assign(widget.el.style, {
            gridColumn: `${col + 1} / span ${colSpan}`,
            gridRow: `${row + 1} / span ${rowSpan}`,
            position: "relative",
            minWidth: "0",
            minHeight: widget.isMinimized() ? "auto" : "0",
            height: widget.isMinimized() ? "auto" : "100%",
        });
        console.log(`[GridLayout] renderWidget: ${widget.id}`, { style: widget.el.style.cssText, gridColumn: widget.el.style.gridColumn, gridRow: widget.el.style.gridRow });
        widget.el.dataset.gridCol = String(col);
        widget.el.dataset.gridRow = String(row);
        widget.el.dataset.gridColSpan = String(colSpan);
        widget.el.dataset.gridRowSpan = String(rowSpan);
    }
    // === Drag and Drop ===
    beginDrag(widget, ev) {
        const entry = this.widgets.get(widget.id);
        if (!entry)
            return;
        const rect = widget.el.getBoundingClientRect();
        // Crear ghost visual
        const ghost = el("div", { class: "widget-drag-ghost" });
        Object.assign(ghost.style, {
            position: "fixed",
            width: cssPx(rect.width),
            height: cssPx(rect.height),
            left: cssPx(rect.left),
            top: cssPx(rect.top),
            pointerEvents: "none",
            zIndex: "10000",
            opacity: "0.8",
            borderRadius: "12px",
            background: "rgba(59, 130, 246, 0.1)",
            border: "2px solid rgba(59, 130, 246, 0.5)",
            backdropFilter: "blur(4px)",
        });
        document.body.appendChild(ghost);
        this.drag = {
            widget,
            startX: ev.clientX,
            startY: ev.clientY,
            offsetX: ev.clientX - rect.left,
            offsetY: ev.clientY - rect.top,
            originalPlacement: { ...entry.placement },
            ghost,
        };
        widget.el.classList.add("is-dragging");
        // Crear preview de drop
        this.createDropPreview();
        const onMove = (e) => this.handleDragMove(e);
        const onUp = (e) => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            this.handleDragEnd(e);
        };
        window.addEventListener("pointermove", onMove, true);
        window.addEventListener("pointerup", onUp, true);
    }
    handleDragMove(ev) {
        if (!this.drag)
            return;
        const { ghost, originalPlacement, widget } = this.drag;
        const rect = widget.el.getBoundingClientRect();
        // Mover ghost manteniendo el offset relativo
        const ghostLeft = ev.clientX - this.drag.offsetX;
        const ghostTop = ev.clientY - this.drag.offsetY;
        ghost.style.left = cssPx(ghostLeft);
        ghost.style.top = cssPx(ghostTop);
        // Calcular celda destino usando la esquina superior izquierda del ghost
        const cell = this.cellFromPoint(ghostLeft, ghostTop);
        if (!cell) {
            this.hideDropPreview();
            this.activeDropZone = null;
            return;
        }
        // Determinar zona de drop
        const dropZone = this.computeDropZone(cell, ev, originalPlacement);
        this.activeDropZone = dropZone;
        this.updateDropPreview(dropZone);
    }
    handleDragEnd(ev) {
        if (!this.drag)
            return;
        const { widget, ghost, originalPlacement } = this.drag;
        widget.el.classList.remove("is-dragging");
        ghost.remove();
        this.hideDropPreview();
        if (this.activeDropZone?.isValid) {
            const { zone, targetWidget, previewPlacement } = this.activeDropZone;
            if (zone === "swap" && targetWidget) {
                const target = this.widgets.get(targetWidget)?.widget;
                if (target) {
                    this.swapWidgets(widget, target);
                }
            }
            else {
                this.moveWidget(widget, previewPlacement);
            }
        }
        this.drag = null;
        this.activeDropZone = null;
    }
    cellFromPoint(x, y) {
        const rect = this.el.getBoundingClientRect();
        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
            return null;
        }
        const { cols, rows, gap } = this.config;
        const contentWidth = rect.width - gap * 2;
        const contentHeight = rect.height - gap * 2;
        const cellWidth = contentWidth / cols;
        const cellHeight = contentHeight / rows;
        const col = Math.floor((x - rect.left - gap) / cellWidth);
        const row = Math.floor((y - rect.top - gap) / cellHeight);
        return {
            col: clamp(col, 0, cols - 1),
            row: clamp(row, 0, rows - 1),
        };
    }
    computeDropZone(cell, ev, originalPlacement) {
        const { row, col } = cell;
        const { cols, rows } = this.config;
        const { rowSpan, colSpan } = originalPlacement;
        // Buscar widget en la celda destino (para swap)
        const targetEntry = this.findWidgetAtCell(row, col);
        // Si hay un widget diferente, ofrecer swap
        if (targetEntry && targetEntry.widget.id !== this.drag?.widget.id) {
            return {
                zone: "swap",
                targetWidget: targetEntry.widget.id,
                targetPlacement: targetEntry.placement,
                previewPlacement: targetEntry.placement,
                isValid: true,
            };
        }
        // Calcular placement donde quepa el widget
        const targetRow = clamp(row, 0, rows - rowSpan);
        const targetCol = clamp(col, 0, cols - colSpan);
        let previewPlacement = {
            row: targetRow,
            col: targetCol,
            rowSpan,
            colSpan,
        };
        // Verificar si hay colisión (excepto con el widget que estamos arrastrando)
        let isValid = this.canPlace(previewPlacement, this.drag?.widget.id);
        if (!isValid) {
            // Intento de auto-redimensionamiento si hay colisión
            // Calculamos cuánto espacio hay realmente disponible en esa posición
            // Usamos row y col originales del 'cell' porque targetRow/targetCol ya están ajustados para el tamaño original
            const effectiveRow = clamp(row, 0, rows - 1);
            const effectiveCol = clamp(col, 0, cols - 1);
            // Calculamos ancho disponible considerando que queremos mantener la altura (rowSpan)
            const availableWidth = this.calculateAvailableWidth(effectiveRow, effectiveCol, rowSpan, this.drag?.widget.id);
            // Si el espacio disponible es menor que el original PERO suficiente (>= minCellSpan)
            if (availableWidth < colSpan && availableWidth >= this.config.minCellSpan) {
                // Probamos con el nuevo tamaño
                const resizedPlacement = {
                    row: effectiveRow,
                    col: effectiveCol,
                    rowSpan,
                    colSpan: availableWidth
                };
                if (this.canPlace(resizedPlacement, this.drag?.widget.id)) {
                    previewPlacement = resizedPlacement;
                    isValid = true;
                }
            }
        }
        return {
            zone: "center",
            previewPlacement,
            isValid,
        };
    }
    calculateAvailableWidth(row, col, rowSpan, excludeId) {
        const { cols } = this.config;
        let available = 0;
        // Verificamos columna por columna hacia la derecha
        for (let c = col; c < cols; c++) {
            // Creamos una "rebanada" de 1 columna de ancho y la altura deseada
            const slice = {
                row: row,
                col: c,
                rowSpan: rowSpan,
                colSpan: 1
            };
            // Si esta rebanada cabe, sumamos 1 al ancho disponible
            if (this.canPlace(slice, excludeId)) {
                available++;
            }
            else {
                // Si encontramos un obstáculo, paramos
                break;
            }
        }
        return available;
    }
    findWidgetAtCell(row, col) {
        for (const entry of this.widgets.values()) {
            const p = entry.placement;
            if (row >= p.row && row < p.row + p.rowSpan &&
                col >= p.col && col < p.col + p.colSpan) {
                return entry;
            }
        }
        return null;
    }
    canPlace(placement, excludeId) {
        for (const [id, entry] of this.widgets) {
            if (id === excludeId)
                continue;
            if (this.placementsOverlap(placement, entry.placement)) {
                return false;
            }
        }
        return true;
    }
    placementsOverlap(a, b) {
        return !(a.col >= b.col + b.colSpan ||
            a.col + a.colSpan <= b.col ||
            a.row >= b.row + b.rowSpan ||
            a.row + a.rowSpan <= b.row);
    }
    // === Drop Preview ===
    createDropPreview() {
        if (this.dropPreview)
            return;
        this.dropPreview = el("div", { class: "grid-drop-preview" });
        Object.assign(this.dropPreview.style, {
            position: "absolute",
            pointerEvents: "none",
            zIndex: "100",
            display: "none",
            borderRadius: "12px",
            transition: "all 0.15s ease",
        });
        this.el.appendChild(this.dropPreview);
    }
    updateDropPreview(zone) {
        if (!this.dropPreview)
            return;
        const { previewPlacement, isValid, zone: zoneType } = zone;
        const { row, col, rowSpan, colSpan } = previewPlacement;
        Object.assign(this.dropPreview.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gridColumn: `${col + 1} / span ${colSpan}`,
            gridRow: `${row + 1} / span ${rowSpan}`,
            background: isValid
                ? "rgba(34, 197, 94, 0.15)"
                : "rgba(239, 68, 68, 0.15)",
            border: `2px dashed ${isValid ? "#22c55e" : "#ef4444"}`,
        });
        // Mostrar indicador de acción
        const label = zoneType === "swap" ? "⇄ Swap" : isValid ? "✓ Drop" : "✗ No space";
        this.dropPreview.textContent = label;
        this.dropPreview.style.color = isValid ? "#22c55e" : "#ef4444";
        this.dropPreview.style.fontWeight = "600";
        this.dropPreview.style.fontSize = "0.875rem";
    }
    hideDropPreview() {
        if (this.dropPreview) {
            this.dropPreview.style.display = "none";
        }
    }
    // === Resize ===
    beginResize(widget, ev) {
        const entry = this.widgets.get(widget.id);
        if (!entry)
            return;
        ev.preventDefault();
        ev.stopPropagation();
        const startX = ev.clientX;
        const startY = ev.clientY;
        const startPlacement = { ...entry.placement };
        const gridRect = this.el.getBoundingClientRect();
        const { cols, rows, gap, minCellSpan } = this.config;
        const cellWidth = (gridRect.width - gap * 2) / cols;
        const cellHeight = (gridRect.height - gap * 2) / rows;
        const onMove = (e) => {
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            const dCols = Math.round(dx / cellWidth);
            const dRows = Math.round(dy / cellHeight);
            const newColSpan = clamp(startPlacement.colSpan + dCols, minCellSpan, cols - startPlacement.col);
            const newRowSpan = clamp(startPlacement.rowSpan + dRows, minCellSpan, rows - startPlacement.row);
            // Verificar si el nuevo tamaño causa colisiones
            const newPlacement = {
                ...startPlacement,
                colSpan: newColSpan,
                rowSpan: newRowSpan,
            };
            if (this.canPlace(newPlacement, widget.id)) {
                entry.placement = newPlacement;
                this.renderWidget(widget, newPlacement);
            }
        };
        const onUp = () => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            widget.setPlacement(entry.placement);
            this.saveState();
        };
        window.addEventListener("pointermove", onMove, true);
        window.addEventListener("pointerup", onUp, true);
    }
    // === Space Finding ===
    findFreeSpace(colSpan, rowSpan) {
        const { cols, rows } = this.config;
        for (let row = 0; row <= rows - rowSpan; row++) {
            for (let col = 0; col <= cols - colSpan; col++) {
                const placement = { row, col, rowSpan, colSpan };
                if (this.canPlace(placement)) {
                    return placement;
                }
            }
        }
        return null;
    }
    normalizePlacement(p) {
        const { cols, rows, minCellSpan } = this.config;
        return {
            row: clamp(p.row, 0, rows - 1),
            col: clamp(p.col, 0, cols - 1),
            rowSpan: clamp(p.rowSpan, minCellSpan, rows),
            colSpan: clamp(p.colSpan, minCellSpan, cols),
        };
    }
    resolveCollisions(widgetId, placement) {
        if (this.canPlace(placement, widgetId)) {
            return placement;
        }
        // Buscar espacio libre cercano
        const free = this.findFreeSpace(placement.colSpan, placement.rowSpan);
        if (free)
            return free;
        // Si no hay espacio, reducir tamaño
        const minPlacement = {
            ...placement,
            rowSpan: this.config.minCellSpan,
            colSpan: this.config.minCellSpan,
        };
        const freeSmall = this.findFreeSpace(minPlacement.colSpan, minPlacement.rowSpan);
        return freeSmall ?? { row: 0, col: 0, rowSpan: 2, colSpan: 2 };
    }
    // === Persistence ===
    storageKey() {
        return `grid-layout:${this.dashboard.id}`;
    }
    saveState() {
        const placements = {};
        for (const [id, entry] of this.widgets) {
            placements[id] = entry.placement;
        }
        storage.set(this.storageKey(), {
            placements,
            preset: this.currentPreset
        });
    }
    loadState() {
        const state = storage.get(this.storageKey());
        if (state?.preset) {
            this.setPreset(state.preset);
        }
        // State will be applied when widgets are added
        if (state?.placements) {
            this.savedPlacements = state.placements;
        }
    }
    getSavedPlacement(widgetId) {
        const saved = this.savedPlacements;
        return saved?.[widgetId] ?? null;
    }
    reset() {
        storage.remove(this.storageKey());
        // Re-layout all widgets in default grid
        let col = 0;
        let row = 0;
        const defaultSpan = 4;
        for (const entry of this.widgets.values()) {
            entry.placement = { row, col, rowSpan: defaultSpan, colSpan: defaultSpan };
            this.renderWidget(entry.widget, entry.placement);
            col += defaultSpan;
            if (col >= this.config.cols) {
                col = 0;
                row += defaultSpan;
            }
        }
        this.saveState();
    }
    destroy() {
        this.saveState();
        for (const d of this.disposers)
            d();
        this.dropPreview?.remove();
    }
}
//# sourceMappingURL=grid-layout.js.map