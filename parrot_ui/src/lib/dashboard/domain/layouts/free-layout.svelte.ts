/**
 * FreeLayout - Absolute positioning layout with drag and resize
 * Domain layer - NO direct DOM manipulation
 */

import type { DashboardTab } from '../dashboard-tab.svelte.js';
import type { Widget } from '../widget.svelte.js';
import { LayoutBase } from './layout-base.svelte.js';
import { storageSync as storage } from '../persistence.js';

// === Types ===

export interface FreePosition {
    x: number;
    y: number;
    width: number;
    height: number;
    zIndex: number;
}

export interface FreeConfig {
    minWidth: number;
    minHeight: number;
    snapToGrid: boolean;
    gridSize: number;
}

// === FreeLayout Class ===

export class FreeLayout extends LayoutBase {
    // Configuration
    config = $state<FreeConfig>({
        minWidth: 150,
        minHeight: 100,
        snapToGrid: false,
        gridSize: 20
    });

    // Widget positions
    #positions = $state<Map<string, FreePosition>>(new Map());

    // Next z-index for stacking
    #nextZIndex = $state(1);

    /**
     * Helper to clone map for reactivity
     */
    #triggerUpdate() {
        this.#positions = new Map(this.#positions);
    }

    // Drag state
    dragState = $state<{
        active: boolean;
        widgetId: string | null;
        startX: number;
        startY: number;
        offsetX: number;
        offsetY: number;
    }>({ active: false, widgetId: null, startX: 0, startY: 0, offsetX: 0, offsetY: 0 });

    // Resize state
    resizeState = $state<{
        active: boolean;
        widgetId: string | null;
        handle: 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw' | null;
        startWidth: number;
        startHeight: number;
        startX: number;
        startY: number;
        startPosX: number;
        startPosY: number;
    } | null>(null);

    constructor(tab: DashboardTab, config?: Partial<FreeConfig>) {
        super(tab);
        if (config) {
            this.config = { ...this.config, ...config };
        }
        this.loadState();
    }

    // === Getters ===

    get positions(): Map<string, FreePosition> {
        return this.#positions;
    }

    getPosition(widgetId: string): FreePosition | undefined {
        return this.#positions.get(widgetId);
    }

    // === Widget Management ===

    addWidget(widget: Widget, placement?: Partial<FreePosition>): void {
        const position = this.#createDefaultPosition(placement);

        this.widgets.set(widget.id, widget);
        this.#positions.set(widget.id, position);

        widget.attach(this.tab, position);
        this.saveState();
    }

    #createDefaultPosition(placement?: Partial<FreePosition>): FreePosition {
        // Cascade placement for new widgets
        const existingCount = this.widgets.size;
        const offset = existingCount * 30;

        return {
            x: placement?.x ?? 50 + offset,
            y: placement?.y ?? 50 + offset,
            width: placement?.width ?? 300,
            height: placement?.height ?? 200,
            zIndex: this.#nextZIndex++
        };
    }

    removeWidget(widget: Widget): void {
        this.widgets.delete(widget.id);
        this.#positions.delete(widget.id);
        widget.detach();
        this.saveState();
    }

    moveWidget(widget: Widget, newPosition: Partial<FreePosition>): void {
        const current = this.#positions.get(widget.id);
        if (!current) return;

        const updated = { ...current, ...newPosition };

        // Apply grid snapping if enabled
        if (this.config.snapToGrid) {
            updated.x = Math.round(updated.x / this.config.gridSize) * this.config.gridSize;
            updated.y = Math.round(updated.y / this.config.gridSize) * this.config.gridSize;
        }

        this.#positions.set(widget.id, updated);
        widget.updatePlacement(updated);
        this.saveState();
    }

    resizeWidget(widget: Widget, newSize: { width: number; height: number }): void {
        const current = this.#positions.get(widget.id);
        if (!current) return;

        const updated = {
            ...current,
            width: Math.max(this.config.minWidth, newSize.width),
            height: Math.max(this.config.minHeight, newSize.height)
        };

        // Apply grid snapping if enabled
        if (this.config.snapToGrid) {
            updated.width = Math.round(updated.width / this.config.gridSize) * this.config.gridSize;
            updated.height = Math.round(updated.height / this.config.gridSize) * this.config.gridSize;
        }

        this.#positions.set(widget.id, updated);
        widget.updatePlacement(updated);

        this.#triggerUpdate();
        this.saveState();
    }

    // === Z-Index Management ===

    bringToFront(widgetId: string): void {
        const position = this.#positions.get(widgetId);
        if (!position) return;

        position.zIndex = this.#nextZIndex++;
        this.saveState();
    }

    sendToBack(widgetId: string): void {
        const position = this.#positions.get(widgetId);
        if (!position) return;

        // Find minimum zIndex and go below it
        let minZ = Infinity;
        for (const pos of this.#positions.values()) {
            if (pos.zIndex < minZ) minZ = pos.zIndex;
        }

        position.zIndex = Math.max(1, minZ - 1);
        this.saveState();
    }

    // === Drag Operations ===

    startDrag(widgetId: string, clientX: number, clientY: number): void {
        const position = this.#positions.get(widgetId);
        if (!position) return;

        this.bringToFront(widgetId);

        this.dragState = {
            active: true,
            widgetId,
            startX: clientX,
            startY: clientY,
            offsetX: position.x,
            offsetY: position.y
        };
    }

    updateDrag(clientX: number, clientY: number): void {
        if (!this.dragState.active || !this.dragState.widgetId) return;

        const dx = clientX - this.dragState.startX;
        const dy = clientY - this.dragState.startY;

        let newX = this.dragState.offsetX + dx;
        let newY = this.dragState.offsetY + dy;

        // Snap to grid if enabled
        if (this.config.snapToGrid) {
            newX = Math.round(newX / this.config.gridSize) * this.config.gridSize;
            newY = Math.round(newY / this.config.gridSize) * this.config.gridSize;
        }

        // Constrain to positive values
        newX = Math.max(0, newX);
        newY = Math.max(0, newY);

        const position = this.#positions.get(this.dragState.widgetId);
        if (position) {
            position.x = newX;
            position.y = newY;
        }
    }

    endDrag(): void {
        if (this.dragState.active && this.dragState.widgetId) {
            const widget = this.widgets.get(this.dragState.widgetId);
            const position = this.#positions.get(this.dragState.widgetId);
            if (widget && position) {
                widget.updatePlacement(position);
            }
        }

        this.dragState = { active: false, widgetId: null, startX: 0, startY: 0, offsetX: 0, offsetY: 0 };
        this.saveState();
    }

    cancelDrag(): void {
        if (this.dragState.active && this.dragState.widgetId) {
            // Restore original position
            const position = this.#positions.get(this.dragState.widgetId);
            if (position) {
                position.x = this.dragState.offsetX;
                position.y = this.dragState.offsetY;
            }
        }
        this.dragState = { active: false, widgetId: null, startX: 0, startY: 0, offsetX: 0, offsetY: 0 };
    }

    // === Resize Operations ===

    startResize(
        widgetId: string,
        handle: 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw',
        clientX: number,
        clientY: number
    ): void {
        const position = this.#positions.get(widgetId);
        if (!position) return;

        this.bringToFront(widgetId);

        this.resizeState = {
            active: true,
            widgetId,
            handle,
            startWidth: position.width,
            startHeight: position.height,
            startX: clientX,
            startY: clientY,
            startPosX: position.x,
            startPosY: position.y
        };
    }

    updateResize(clientX: number, clientY: number): void {
        if (!this.resizeState?.active || !this.resizeState.widgetId) return;

        const position = this.#positions.get(this.resizeState.widgetId);
        if (!position) return;

        const dx = clientX - this.resizeState.startX;
        const dy = clientY - this.resizeState.startY;
        const { handle, startWidth, startHeight, startPosX, startPosY } = this.resizeState;

        let newWidth = startWidth;
        let newHeight = startHeight;
        let newX = startPosX;
        let newY = startPosY;

        // Calculate new dimensions based on handle
        if (handle && handle.includes('e')) newWidth = startWidth + dx;
        if (handle && handle.includes('w')) {
            newWidth = startWidth - dx;
            newX = startPosX + dx;
        }
        if (handle && handle.includes('s')) newHeight = startHeight + dy;
        if (handle && handle.includes('n')) {
            newHeight = startHeight - dy;
            newY = startPosY + dy;
        }

        // Apply minimums
        newWidth = Math.max(this.config.minWidth, newWidth);
        newHeight = Math.max(this.config.minHeight, newHeight);

        // Apply grid snapping
        if (this.config.snapToGrid) {
            newWidth = Math.round(newWidth / this.config.gridSize) * this.config.gridSize;
            newHeight = Math.round(newHeight / this.config.gridSize) * this.config.gridSize;
            newX = Math.round(newX / this.config.gridSize) * this.config.gridSize;
            newY = Math.round(newY / this.config.gridSize) * this.config.gridSize;
        }

        position.width = newWidth;
        position.height = newHeight;
        position.x = Math.max(0, newX);
        position.y = Math.max(0, newY);

        this.#triggerUpdate();
    }

    endResize(): void {
        if (this.resizeState?.active && this.resizeState.widgetId) {
            const widget = this.widgets.get(this.resizeState.widgetId);
            const position = this.#positions.get(this.resizeState.widgetId);
            if (widget && position) {
                widget.updatePlacement(position);
            }
        }
        this.resizeState = null;
        this.saveState();
    }

    // === Persistence ===

    protected override get storageKey(): string {
        return `free-layout-${this.tab.id}`;
    }

    saveState(): void {
        const state = {
            positions: Object.fromEntries(this.#positions),
            nextZIndex: this.#nextZIndex,
            config: this.config
        };
        storage.set(this.storageKey, state);
    }

    loadState(): void {
        const state = storage.get<{
            positions?: Record<string, FreePosition>;
            nextZIndex?: number;
            config?: Partial<FreeConfig>;
        }>(this.storageKey);

        if (state?.nextZIndex) {
            this.#nextZIndex = state.nextZIndex;
        }

        if (state?.config) {
            this.config = { ...this.config, ...state.config };
        }
    }

    serialize(): unknown {
        // FreeLayout needs to save position/size which should be in the widget state or layout state.
        // Assuming widget.toJSON() saves floating/position state if it's stored on widget.
        // If layout stores it, we need to extract it.
        return Array.from(this.widgets.values()).map(w => w.toJSON());
    }

    reset(): void {
        storage.remove(this.storageKey);
        this.#nextZIndex = 1;

        // Reset all positions to default cascade
        let offset = 0;
        for (const [id, widget] of this.widgets) {
            const position: FreePosition = {
                x: 50 + offset,
                y: 50 + offset,
                width: 300,
                height: 200,
                zIndex: this.#nextZIndex++
            };
            this.#positions.set(id, position);
            widget.updatePlacement(position);
            offset += 30;
        }
        this.saveState();
    }
}
