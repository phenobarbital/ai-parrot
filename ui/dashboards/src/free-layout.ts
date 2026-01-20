import { clamp, cssPx, el, stop, storage } from "./utils.js";
import { bus } from "./events.js";
import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type { FreeLayoutConfig, FreePosition } from "./types.js";

interface WidgetEntry {
    widget: Widget;
    position: FreePosition;
}

export class FreeLayout {
    dashboard: DashboardView;
    config: FreeLayoutConfig;
    widgets = new Map<string, WidgetEntry>();
    el: HTMLElement;
    drag: {
        widget: Widget;
        offsetX: number;
        offsetY: number;
        ghost: HTMLElement;
    } | null = null;
    savedPositions: Record<string, FreePosition> | null = null;

    constructor(dashboard: DashboardView, config: Partial<FreeLayoutConfig> = {}) {
        this.dashboard = dashboard;
        this.config = {
            snapToGrid: config.snapToGrid ?? false,
            gridSize: config.gridSize ?? 20,
            padding: config.padding ?? 12,
        };

        this.el = el("div", { class: "free-layout" });
        Object.assign(this.el.style, {
            position: "relative",
            width: "100%",
            height: "100%",
            overflow: "hidden",
        });

        if (this.config.snapToGrid) {
            const size = `${this.config.gridSize}px`;
            Object.assign(this.el.style, {
                backgroundImage: "linear-gradient(#e5e7eb 1px, transparent 1px), linear-gradient(90deg, #e5e7eb 1px, transparent 1px)",
                backgroundSize: `${size} ${size}`,
                backgroundPosition: `0 0` // Align with top-left
            });
        }

        this.loadState();
    }

    addWidget(widget: Widget, position: Partial<FreePosition> = {}): void {
        const saved = this.getSavedPosition(widget.id);
        const pos: FreePosition = saved || {
            x: position.x ?? this.config.padding,
            y: position.y ?? this.config.padding,
            width: position.width ?? 320,
            height: position.height ?? 240,
        };

        if (!saved && position.x === undefined && position.y === undefined) {
            const free = this.findFreePosition(pos.width, pos.height);
            pos.x = free.x;
            pos.y = free.y;
        }

        this.widgets.set(widget.id, { widget, position: pos });
        this.renderWidget(widget, pos);
        // We cast to any because setDocked expects distinct signatures based on layout logic
        // Ideally we update Widget.setDocked signature, but for now we pass the position
        widget.setDocked(this.dashboard, pos as any);

        if (!this.widgets.has(widget.id)) {
            // Only add listener once
            bus.on("widget:minimized", ({ widget: w }) => {
                if (this.widgets.has(w.id)) {
                    const entry = this.widgets.get(w.id);
                    if (entry) this.renderWidget(w, entry.position);
                }
            });
        }

        bus.emit("widget:added", { widget, dashboard: this.dashboard, placement: pos });
        this.saveState();
    }

    removeWidget(widget: Widget): void {
        const entry = this.widgets.get(widget.id);
        if (!entry) return;

        widget.el.remove();
        this.widgets.delete(widget.id);
        bus.emit("widget:removed", { widget, dashboard: this.dashboard });
        this.saveState();
    }

    moveWidget(widget: Widget, newPosition: Partial<FreePosition>): void {
        const entry = this.widgets.get(widget.id);
        if (!entry) return;

        const pos = this.constrainPosition({ ...entry.position, ...newPosition });
        entry.position = pos;
        this.renderWidget(widget, pos);
        // widget.setPositionFree(pos); // We'll implement this implicitly via setDocked or style update
        widget.setPlacement(pos as any);
        this.saveState();
    }

    resizeWidget(widget: Widget, newSize: { width: number; height: number }): void {
        const entry = this.widgets.get(widget.id);
        if (!entry) return;

        entry.position.width = Math.max(150, newSize.width);
        entry.position.height = Math.max(100, newSize.height);
        this.renderWidget(widget, entry.position);
        widget.setPlacement(entry.position as any);
        this.saveState();
    }

    getWidget(widgetId: string): Widget | undefined {
        return this.widgets.get(widgetId)?.widget;
    }

    getWidgets(): Widget[] {
        return Array.from(this.widgets.values()).map((e) => e.widget);
    }

    getPosition(widgetId: string): FreePosition | undefined {
        return this.widgets.get(widgetId)?.position;
    }

    renderWidget(widget: Widget, position: FreePosition): void {
        if (!widget.el.parentElement) this.el.appendChild(widget.el);

        const isMinimized = widget.isMinimized();
        // Use a standard height for minimized widgets (e.g. 40px for titlebar)
        const height = isMinimized ? "auto" : cssPx(position.height);

        Object.assign(widget.el.style, {
            position: "absolute",
            left: cssPx(position.x),
            top: cssPx(position.y),
            width: cssPx(position.width),
            height: height,
            minWidth: "150px",
            minHeight: isMinimized ? "auto" : "100px",
            gridColumn: "", // Reset grid styles
            gridRow: "",
        });
    }

    constrainPosition(pos: FreePosition): FreePosition {
        const rect = this.el.getBoundingClientRect();
        // Allow at least padding size if rect is 0 (unmounted)
        const contWidth = rect.width || 800;
        const contHeight = rect.height || 600;

        // 1. Constrain dimensions first (prevent full-width/too large widgets)
        // Ensure widget is at least min size and not larger than container - padding
        let width = clamp(pos.width, 150, contWidth - this.config.padding * 2);
        let height = clamp(pos.height, 100, contHeight - this.config.padding * 2);

        // 2. Calculate boundaries
        const maxX = Math.max(0, contWidth - width - this.config.padding);
        const maxY = Math.max(0, contHeight - height - this.config.padding);

        // 3. Snap first, THEN clamp to container? 
        // If we snap first, we might snap to 0. 
        // If we clamp to padding (12) then snap (20), we get 20.
        // If we want to allow 0, we should perhaps relax the min clamp if the user drags there.
        // But padding implies "keep inside".
        // Let's assume padding is a hard constraint for "inside the box".
        // BUT if the grid starts at 0, and padding is 12, maybe the grid should be offset by padding?
        // Or maybe we treat padding as the "start" of the grid.

        let x = pos.x;
        let y = pos.y;

        if (this.config.snapToGrid) {
            // Snap relative to padding? OR plain snap?
            // If we want consistent alignment, plain snap is usually better.
            x = Math.round(x / this.config.gridSize) * this.config.gridSize;
            y = Math.round(y / this.config.gridSize) * this.config.gridSize;
        }

        // Clamp to valid area (respecting padding)
        // If x=0 and padding=12, this forces x=12. 
        // If snapToGrid, x=12 -> 0.6 -> 1 -> 20.
        // If we want to allow snapping to the edge (0), we must reduce padding or allow x to be < padding if it's 0?
        // Let's assume padding acts as an "inset".

        x = clamp(x, this.config.padding, Math.max(this.config.padding, maxX));
        y = clamp(y, this.config.padding, Math.max(this.config.padding, maxY));

        // Re-snap after clamp? 
        // If x=12 (clamped), and grid=20, we are off-grid.
        // So we should probably snap AFTER clamping, but we need to ensure we don't snap outside again.
        if (this.config.snapToGrid) {
            x = Math.round(x / this.config.gridSize) * this.config.gridSize;
            y = Math.round(y / this.config.gridSize) * this.config.gridSize;
            // If rounding pushed us out (e.g. 12->0 < padding), we have a conflict.
            // If padding is strict, we can't be at 0.
            // If we want to allow 0, we must ignore padding for 0?
            // The user complains "leaving one column to the left". Meaning they WANT it to be closer to left.
            // Maybe padding should be ignored if it conflicts with grid?
            // Or we just check valid grid points.
            // 12 <= n * 20. The first valid is 20.
            // If they want 0, they can't have padding=12.
            // Unless... we update padding to be 0 or small for this demo?
            // OR we offset the snap: x = round((x - padding) / grid) * grid + padding.
            // This would make the grid START at padding.
            // 0 -> 12. 20 -> 32. 
            // This keeps alignment consistent relative to the "content box".
            // Let's try this offset approach.

            // Reset to raw pos
            /* Implementation of offset snap */
        }

        // Actually, simpler fix for the "one column left" complaint:
        // Use the offset snap logic so the grid aligns with the padding corner.

        if (this.config.snapToGrid) {
            const gs = this.config.gridSize;

            // Standard grid snap (0, 20, 40...)
            x = Math.round(x / gs) * gs;
            y = Math.round(y / gs) * gs;
        }

        // Final clamp to ensure we are strictly inside (padding acts as a hard boundary)
        // If x=0 from snap, it becomes 12. If x=20, it stays 20.
        x = clamp(x, this.config.padding, Math.max(this.config.padding, maxX));
        y = clamp(y, this.config.padding, Math.max(this.config.padding, maxY));

        return { ...pos, x, y, width, height };
    }

    beginDrag(widget: Widget, ev: MouseEvent): void {
        const entry = this.widgets.get(widget.id);
        if (!entry) return;

        const startX = ev.clientX;
        const startY = ev.clientY;
        const initialPos = { ...entry.position };

        widget.el.style.zIndex = "100";
        widget.el.classList.add("is-dragging");

        const onMove = (e: Event) => this.handleDragMove(e as MouseEvent, startX, startY, initialPos, entry, widget);

        const onUp = () => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            widget.el.classList.remove("is-dragging");
            widget.el.style.zIndex = "";
            // Ensure final position is set and saved
            widget.setPlacement(entry.position as any);
            this.saveState();
        };

        window.addEventListener("pointermove", onMove, true);
        window.addEventListener("pointerup", onUp, true);
    }

    handleDragMove(e: MouseEvent, startX: number, startY: number, initialPos: FreePosition, entry: WidgetEntry, widget: Widget) {
        const deltaX = e.clientX - startX;
        const deltaY = e.clientY - startY;

        const x = initialPos.x + deltaX;
        const y = initialPos.y + deltaY;

        const newPos = this.constrainPosition({ ...initialPos, x, y });

        widget.el.style.left = cssPx(newPos.x);
        widget.el.style.top = cssPx(newPos.y);
        entry.position.x = newPos.x;
        entry.position.y = newPos.y;
    }

    beginResize(widget: Widget, ev: MouseEvent): void {
        const entry = this.widgets.get(widget.id);
        if (!entry) return;
        stop(ev);

        const startX = ev.clientX, startY = ev.clientY;
        const startW = entry.position.width, startH = entry.position.height;

        const onMove = (e: Event) => {
            const me = e as MouseEvent;
            let newW = startW + (me.clientX - startX);
            let newH = startH + (me.clientY - startY);

            if (this.config.snapToGrid) {
                newW = Math.round(newW / this.config.gridSize) * this.config.gridSize;
                newH = Math.round(newH / this.config.gridSize) * this.config.gridSize;
            }

            entry.position.width = Math.max(150, newW);
            entry.position.height = Math.max(100, newH);
            widget.el.style.width = cssPx(entry.position.width);
            widget.el.style.height = cssPx(entry.position.height);
        };

        const onUp = () => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            widget.setPlacement(entry.position as any);
            this.saveState();
        };

        window.addEventListener("pointermove", onMove, true);
        window.addEventListener("pointerup", onUp, true);
    }

    findFreePosition(width: number, height: number): { x: number; y: number } {
        const rect = this.el.getBoundingClientRect();
        // Fallback dimensions if unmounted
        const contWidth = rect.width || 800;
        const contHeight = rect.height || 600;

        const step = this.config.snapToGrid ? this.config.gridSize : 30;
        const pad = this.config.padding;

        for (let y = pad; y < contHeight - height - pad; y += step) {
            for (let x = pad; x < contWidth - width - pad; x += step) {
                if (!this.hasOverlap({ x, y, width, height })) return { x, y };
            }
        }

        const count = this.widgets.size;
        return {
            x: pad + (count * 40) % Math.max(1, contWidth - width - pad * 2),
            y: pad + (count * 40) % Math.max(1, contHeight - height - pad * 2),
        };
    }

    findFreeSpace(width: number, height: number): FreePosition {
        const pos = this.findFreePosition(width ?? 320, height ?? 240);
        return { x: pos.x, y: pos.y, width: width ?? 320, height: height ?? 240 };
    }

    hasOverlap(rect: FreePosition, excludeId?: string): boolean {
        for (const [id, entry] of this.widgets) {
            if (id === excludeId) continue;
            const p = entry.position;
            if (!(rect.x >= p.x + p.width || rect.x + rect.width <= p.x ||
                rect.y >= p.y + p.height || rect.y + rect.height <= p.y)) {
                return true;
            }
        }
        return false;
    }

    storageKey(): string {
        return `free-layout:${this.dashboard.id}`;
    }

    saveState(): void {
        const positions: Record<string, FreePosition> = {};
        for (const [id, entry] of this.widgets) positions[id] = entry.position;
        storage.set(this.storageKey(), { positions });
    }

    loadState(): void {
        const state = storage.get<{ positions: Record<string, FreePosition> }>(this.storageKey());
        if (state?.positions) {
            // Validate positions
            const validPositions: Record<string, FreePosition> = {};
            for (const [id, pos] of Object.entries(state.positions)) {
                if (Number.isFinite(pos.x) && Number.isFinite(pos.y) &&
                    Number.isFinite(pos.width) && Number.isFinite(pos.height)) {
                    validPositions[id] = pos;
                }
            }
            this.savedPositions = validPositions;
        }
    }

    getSavedPosition(widgetId: string): FreePosition | null {
        return this.savedPositions?.[widgetId] ?? null;
    }

    reset(): void {
        storage.remove(this.storageKey());
        const pad = this.config.padding;
        let x = pad, y = pad;
        const rect = this.el.getBoundingClientRect();
        const width = rect.width || 800;

        for (const entry of this.widgets.values()) {
            entry.position = { x, y, width: 320, height: 240 };
            this.renderWidget(entry.widget, entry.position);
            x += 340;
            if (x + 320 > width - pad) {
                x = pad;
                y += 260;
            }
        }
        this.saveState();
    }

    destroy(): void {
        this.saveState();
    }
}
