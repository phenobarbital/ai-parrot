// dock-layout.ts - Fixed Pane Layout System
// Redesigned to use predefined templates with tabbed widgets per pane

import { el, on, stop, cssPx, uid, storage, type Dispose } from "./utils.js";
import { bus } from "./events.js";
import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type {
    DockLayoutConfig,
    DockPosition,
    Pane,
    PaneStructure,
    PaneLayoutTemplate
} from "./types.js";
import { DOCK_TEMPLATES, getTemplate, LAYOUT_2_COLUMNS } from "./dock-templates.js";

interface DockDragState {
    widget: Widget;
    ghost: HTMLElement;
    offsetX: number;
    offsetY: number;
    targetPane: Pane | null;
}

export class DockLayout {
    readonly dashboard: DashboardView;
    readonly config: DockLayoutConfig;
    readonly el: HTMLElement;

    private panes = new Map<string, Pane>();
    private widgets = new Map<string, Widget>();
    private currentTemplate: PaneLayoutTemplate | null = null;
    private drag: DockDragState | null = null;
    private disposers: Dispose[] = [];

    constructor(dashboard: DashboardView, config: Partial<DockLayoutConfig> = {}) {
        this.dashboard = dashboard;
        this.config = {
            minPanelSize: config.minPanelSize ?? 100,
            gutterSize: config.gutterSize ?? 6,
        };

        this.el = el("div", { class: "dock-layout" });
        Object.assign(this.el.style, {
            display: "flex",
            flexDirection: "column",
            height: "100%",
            position: "relative",
            overflow: "hidden",
        });

        // Apply initial template
        const templateId = config.initialTemplate ?? "2-columns";
        const template = getTemplate(templateId) ?? LAYOUT_2_COLUMNS;
        this.applyTemplate(template);

        // Listen for widget minimized events
        this.disposers.push(
            bus.on("widget:minimized", ({ widget }) => {
                if (!this.widgets.has(widget.id)) return;
                // Just re-render the pane tabs
                for (const pane of this.panes.values()) {
                    if (pane.widgets.includes(widget.id)) {
                        this.renderPaneTabs(pane);
                        break;
                    }
                }
            })
        );
    }

    // === Template Management ===

    applyTemplate(template: PaneLayoutTemplate): void {
        // Save current widget mappings
        const widgetPaneMap = new Map<string, string[]>();
        for (const pane of this.panes.values()) {
            widgetPaneMap.set(pane.id, [...pane.widgets]);
        }

        // Clear current layout
        this.el.innerHTML = "";
        this.panes.clear();
        this.currentTemplate = template;

        // Build new layout
        const rootEl = this.buildStructure(template.structure);
        this.el.appendChild(rootEl);

        // Redistribute widgets to new panes
        const paneIds = Array.from(this.panes.keys());
        if (paneIds.length > 0) {
            let paneIndex = 0;
            for (const widget of this.widgets.values()) {
                const paneId = paneIds[paneIndex % paneIds.length]!;
                const pane = this.panes.get(paneId);
                if (pane) {
                    this.addWidgetToPane(widget, pane, false);
                    paneIndex++;
                }
            }
        }

        bus.emit("dock:template-changed", { template, layout: this });
    }

    private buildStructure(structure: PaneStructure, parentEl?: HTMLElement): HTMLElement {
        if (structure.type === "pane") {
            return this.createPane(structure.id);
        }

        const isRow = structure.type === "row";
        const container = el("div", { class: `dock-${structure.type}` });
        Object.assign(container.style, {
            display: "flex",
            flexDirection: isRow ? "row" : "column",
            flex: "1",
            minWidth: "0",
            minHeight: "0",
        });

        const sizes = structure.sizes ?? structure.children.map(() => 100 / structure.children.length);

        structure.children.forEach((child, i) => {
            const childEl = this.buildStructure(child, container);
            childEl.style.flex = `0 0 ${sizes[i]}%`;
            container.appendChild(childEl);

            // Add gutter between children
            if (i < structure.children.length - 1) {
                const gutter = this.createGutter(container, i, isRow, sizes);
                container.appendChild(gutter);
            }
        });

        return container;
    }

    private createPane(id: string): HTMLElement {
        const paneEl = el("div", { class: "dock-pane", "data-pane-id": id });
        Object.assign(paneEl.style, {
            display: "flex",
            flexDirection: "column",
            minWidth: cssPx(this.config.minPanelSize),
            minHeight: cssPx(this.config.minPanelSize),
            position: "relative",
            overflow: "hidden",
            background: "var(--pane-bg, #f8f9fa)",
            borderRadius: "8px",
            border: "1px solid var(--border, #ddd)",
        });

        // Tab bar
        const tabBar = el("div", { class: "dock-pane-tabs" });
        Object.assign(tabBar.style, {
            display: "flex",
            alignItems: "center",
            gap: "2px",
            padding: "4px 8px",
            background: "var(--pane-header, #e9ecef)",
            borderBottom: "1px solid var(--border, #ddd)",
            minHeight: "32px",
            flexWrap: "wrap",
        });

        // Pane toolbar - chevron dropdown menu
        const toolbar = el("div", { class: "dock-pane-toolbar" });
        Object.assign(toolbar.style, {
            marginLeft: "auto",
            display: "flex",
            position: "relative",
        });

        const menuBtn = el("button", { class: "dock-pane-menu-btn", title: "Pane Options" }, "▾");
        Object.assign(menuBtn.style, {
            background: "transparent",
            border: "none",
            color: "var(--text-muted, #666)",
            cursor: "pointer",
            padding: "2px 8px",
            fontSize: "12px",
        });

        const dropdown = el("div", { class: "dock-pane-dropdown" });
        Object.assign(dropdown.style, {
            display: "none",
            position: "absolute",
            top: "100%",
            right: "0",
            background: "var(--dropdown-bg, #fff)",
            border: "1px solid var(--border, #ddd)",
            borderRadius: "6px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            zIndex: "1000",
            minWidth: "140px",
            overflow: "hidden",
        });

        const menuItems = [
            { label: "Split Horizontal", action: () => this.splitPane(id, "horizontal") },
            { label: "Split Vertical", action: () => this.splitPane(id, "vertical") },
            { divider: true },
            { label: "Close Pane", action: () => this.removePane(id) },
        ];

        for (const item of menuItems) {
            if ((item as any).divider) {
                const hr = el("hr");
                Object.assign(hr.style, { margin: "4px 0", border: "none", borderTop: "1px solid var(--border, #ddd)" });
                dropdown.appendChild(hr);
            } else {
                const btn = el("button", { class: "dock-pane-dropdown-item" }, (item as any).label);
                Object.assign(btn.style, {
                    display: "block",
                    width: "100%",
                    padding: "8px 12px",
                    background: "transparent",
                    border: "none",
                    color: "var(--text, #333)",
                    cursor: "pointer",
                    textAlign: "left",
                    fontSize: "12px",
                });
                this.disposers.push(
                    on(btn, "click", (ev) => { stop(ev); (item as any).action(); dropdown.style.display = "none"; }),
                    on(btn, "mouseenter", () => btn.style.background = "var(--surface, #1a1a2e)"),
                    on(btn, "mouseleave", () => btn.style.background = "transparent")
                );
                dropdown.appendChild(btn);
            }
        }

        this.disposers.push(
            on(menuBtn, "click", (ev) => {
                stop(ev);
                dropdown.style.display = dropdown.style.display === "none" ? "block" : "none";
            }),
            on(document, "click", (ev) => {
                if (!(ev.target as HTMLElement).closest(".dock-pane-toolbar")) {
                    dropdown.style.display = "none";
                }
            })
        );

        toolbar.append(menuBtn, dropdown);
        tabBar.appendChild(toolbar);

        // Content area
        const contentArea = el("div", { class: "dock-pane-content" });
        Object.assign(contentArea.style, {
            flex: "1",
            position: "relative",
            overflow: "hidden",
        });

        // Drop zone overlay
        const dropZone = el("div", { class: "dock-pane-dropzone" });
        Object.assign(dropZone.style, {
            position: "absolute",
            inset: "0",
            display: "none",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(59, 130, 246, 0.1)",
            border: "2px dashed rgba(59, 130, 246, 0.5)",
            borderRadius: "6px",
            pointerEvents: "none",
            zIndex: "10",
        });
        contentArea.appendChild(dropZone);

        paneEl.append(tabBar, contentArea);

        const pane: Pane = {
            id,
            el: paneEl,
            tabBar,
            contentArea,
            widgets: [],
            activeWidget: null,
        };

        this.panes.set(id, pane);

        // Setup drop target
        this.setupPaneDropTarget(pane);

        return paneEl;
    }

    private createGutter(container: HTMLElement, index: number, isHorizontal: boolean, sizes: number[]): HTMLElement {
        const gutter = el("div", { class: "dock-gutter" });
        Object.assign(gutter.style, {
            flex: `0 0 ${this.config.gutterSize}px`,
            background: "var(--border, #333)",
            cursor: isHorizontal ? "col-resize" : "row-resize",
            transition: "background 150ms",
        });

        on(gutter, "mouseenter", () => gutter.style.background = "var(--accent, #3b82f6)");
        on(gutter, "mouseleave", () => gutter.style.background = "var(--border, #333)");

        on(gutter, "pointerdown", (ev) => {
            stop(ev);
            this.beginGutterResize(container, index, isHorizontal, sizes, ev);
        });

        return gutter;
    }

    private beginGutterResize(container: HTMLElement, index: number, isHorizontal: boolean, sizes: number[], ev: PointerEvent): void {
        const startPos = isHorizontal ? ev.clientX : ev.clientY;
        const rect = container.getBoundingClientRect();
        const totalSize = isHorizontal ? rect.width : rect.height;
        const gutterTotal = (sizes.length - 1) * this.config.gutterSize;
        const availableSize = totalSize - gutterTotal;
        const startSizes = [...sizes];

        // Get the actual child elements (skip gutters)
        const children = Array.from(container.children).filter(c => !c.classList.contains("dock-gutter")) as HTMLElement[];

        const onMove = (e: PointerEvent) => {
            const currentPos = isHorizontal ? e.clientX : e.clientY;
            const delta = currentPos - startPos;
            const deltaPercent = (delta / availableSize) * 100;
            const minPercent = (this.config.minPanelSize / availableSize) * 100;

            let newSize1 = startSizes[index]! + deltaPercent;
            let newSize2 = startSizes[index + 1]! - deltaPercent;

            if (newSize1 < minPercent) {
                newSize1 = minPercent;
                newSize2 = startSizes[index]! + startSizes[index + 1]! - minPercent;
            }
            if (newSize2 < minPercent) {
                newSize2 = minPercent;
                newSize1 = startSizes[index]! + startSizes[index + 1]! - minPercent;
            }

            sizes[index] = newSize1;
            sizes[index + 1] = newSize2;

            const child1 = children[index];
            const child2 = children[index + 1];
            if (child1) child1.style.flex = `0 0 ${newSize1}%`;
            if (child2) child2.style.flex = `0 0 ${newSize2}%`;
        };

        const onUp = () => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
        };

        window.addEventListener("pointermove", onMove, true);
        window.addEventListener("pointerup", onUp, true);
    }

    // === Pane Operations ===

    splitPane(paneId: string, direction: "horizontal" | "vertical"): void {
        const pane = this.panes.get(paneId);
        if (!pane) return;

        const parent = pane.el.parentElement;
        if (!parent) return;

        // Capture insertion point BEFORE we move pane.el
        const nextSibling = pane.el.nextSibling;

        // Create new pane
        const newPaneId = uid("pane");
        const newPaneEl = this.createPane(newPaneId);

        // Create wrapper for both panes
        const wrapper = el("div", { class: `dock-${direction === "horizontal" ? "row" : "column"}` });
        Object.assign(wrapper.style, {
            display: "flex",
            flexDirection: direction === "horizontal" ? "row" : "column",
            flex: pane.el.style.flex,
            minWidth: "0",
            minHeight: "0",
        });

        const sizes = [50, 50];
        pane.el.style.flex = `0 0 ${sizes[0]}%`;
        newPaneEl.style.flex = `0 0 ${sizes[1]}%`;

        const gutter = this.createGutter(wrapper, 0, direction === "horizontal", sizes);

        wrapper.append(pane.el, gutter, newPaneEl);

        // Insert wrapper at the original position
        parent.insertBefore(wrapper, nextSibling);

        bus.emit("dock:pane-split", { paneId, newPaneId, direction });
    }

    removePane(paneId: string): void {
        const pane = this.panes.get(paneId);
        if (!pane) return;

        // Move widgets to first available pane
        const otherPane = Array.from(this.panes.values()).find(p => p.id !== paneId);
        if (otherPane) {
            for (const widgetId of pane.widgets) {
                const widget = this.widgets.get(widgetId);
                if (widget) {
                    this.addWidgetToPane(widget, otherPane, false);
                }
            }
        }

        // Remove from DOM
        const parent = pane.el.parentElement;
        pane.el.remove();

        // Clean up parent if it's now empty or has only one child
        if (parent && parent !== this.el) {
            const remainingChildren = Array.from(parent.children).filter(c => !c.classList.contains("dock-gutter"));
            if (remainingChildren.length === 1) {
                // Unwrap single child
                const child = remainingChildren[0] as HTMLElement;
                child.style.flex = parent.style.flex;
                parent.replaceWith(child);
            } else if (remainingChildren.length === 0) {
                parent.remove();
            } else {
                // Remove adjacent gutter
                const gutters = parent.querySelectorAll(".dock-gutter");
                if (gutters.length > 0) gutters[gutters.length - 1]?.remove();
            }
        }

        this.panes.delete(paneId);
        bus.emit("dock:pane-removed", { paneId });
    }

    // === Widget Management ===

    addWidget(widget: Widget, placement: { dockPosition?: DockPosition; paneId?: string } | string = "center"): void {
        this.widgets.set(widget.id, widget);

        // Find target pane
        let targetPane: Pane | undefined;

        if (typeof placement === "object" && placement.paneId) {
            targetPane = this.panes.get(placement.paneId);
        }

        if (!targetPane) {
            // Default to first pane
            targetPane = this.panes.values().next().value;
        }

        if (targetPane) {
            this.addWidgetToPane(widget, targetPane);
        }

        widget.setDocked(this.dashboard, { dockPosition: "center" } as any);
        bus.emit("widget:added", { widget, dashboard: this.dashboard, placement: { dockPosition: "center" } as any });
    }

    private addWidgetToPane(widget: Widget, pane: Pane, emitEvent = true): void {
        // Remove from previous pane if any
        for (const p of this.panes.values()) {
            const idx = p.widgets.indexOf(widget.id);
            if (idx !== -1) {
                p.widgets.splice(idx, 1);
                if (p.activeWidget === widget.id) {
                    p.activeWidget = p.widgets[0] ?? null;
                }
                this.renderPaneTabs(p);
                this.renderPaneContent(p);
            }
        }

        // Add to new pane
        pane.widgets.push(widget.id);
        pane.activeWidget = widget.id;

        this.renderPaneTabs(pane);
        this.renderPaneContent(pane);

        if (emitEvent) {
            bus.emit("widget:moved", { widget, paneId: pane.id });
        }
    }

    removeWidget(widget: Widget): void {
        for (const pane of this.panes.values()) {
            const idx = pane.widgets.indexOf(widget.id);
            if (idx !== -1) {
                pane.widgets.splice(idx, 1);
                if (pane.activeWidget === widget.id) {
                    pane.activeWidget = pane.widgets[0] ?? null;
                }
                this.renderPaneTabs(pane);
                this.renderPaneContent(pane);
                break;
            }
        }

        this.widgets.delete(widget.id);
        widget.el.remove();
        bus.emit("widget:removed", { widget, dashboard: this.dashboard });
    }

    getWidget(widgetId: string): Widget | undefined {
        return this.widgets.get(widgetId);
    }

    getWidgets(): Widget[] {
        return Array.from(this.widgets.values());
    }

    getPlacement(widgetId: string): { dockPosition: DockPosition; paneId?: string } | null {
        for (const pane of this.panes.values()) {
            if (pane.widgets.includes(widgetId)) {
                return { dockPosition: "center", paneId: pane.id };
            }
        }
        return null;
    }

    findFreeSpace(): { dockPosition: DockPosition } {
        return { dockPosition: "center" };
    }

    // === Pane Rendering ===

    private renderPaneTabs(pane: Pane): void {
        // Clear existing tabs (keep toolbar)
        const toolbar = pane.tabBar.querySelector(".dock-pane-toolbar");
        pane.tabBar.innerHTML = "";
        if (toolbar) pane.tabBar.appendChild(toolbar);

        // Prepend tabs before toolbar
        for (const widgetId of pane.widgets) {
            const widget = this.widgets.get(widgetId);
            if (!widget) continue;

            const isActive = pane.activeWidget === widgetId;
            const tab = el("button", {
                class: `dock-tab ${isActive ? "dock-tab-active" : ""}`,
                "data-widget-id": widgetId,
            });

            Object.assign(tab.style, {
                display: "flex",
                alignItems: "center",
                gap: "4px",
                padding: "4px 12px",
                background: isActive ? "var(--surface, #1a1a2e)" : "transparent",
                border: "none",
                borderRadius: "4px 4px 0 0",
                color: isActive ? "var(--text, #fff)" : "var(--text-muted, #888)",
                cursor: "pointer",
                fontSize: "12px",
                fontWeight: isActive ? "600" : "400",
            });

            const icon = el("span", {}, widget.getIcon());
            const title = el("span", {}, widget.getTitle());
            const closeBtn = el("span", { class: "dock-tab-close", title: "Close" }, "×");
            Object.assign(closeBtn.style, {
                marginLeft: "4px",
                opacity: "0.5",
                fontSize: "14px",
            });

            tab.append(icon, title, closeBtn);

            // Tab click to activate
            this.disposers.push(
                on(tab, "click", (ev) => {
                    if ((ev.target as HTMLElement).classList.contains("dock-tab-close")) {
                        widget.close();
                    } else {
                        stop(ev);
                        pane.activeWidget = widgetId;
                        this.renderPaneTabs(pane);
                        this.renderPaneContent(pane);
                    }
                })
            );

            // Tab drag start
            this.disposers.push(
                on(tab, "pointerdown", (ev) => {
                    if ((ev.target as HTMLElement).classList.contains("dock-tab-close")) return;
                    this.beginDrag(widget, ev);
                })
            );

            pane.tabBar.insertBefore(tab, toolbar);
        }
    }

    private renderPaneContent(pane: Pane): void {
        // Hide all widgets in this pane
        for (const widgetId of pane.widgets) {
            const widget = this.widgets.get(widgetId);
            if (widget) {
                widget.el.style.display = "none";
            }
        }

        // Show active widget
        if (pane.activeWidget) {
            const activeWidget = this.widgets.get(pane.activeWidget);
            if (activeWidget) {
                if (activeWidget.el.parentElement !== pane.contentArea) {
                    pane.contentArea.appendChild(activeWidget.el);
                }
                activeWidget.el.style.display = "";
                Object.assign(activeWidget.el.style, {
                    position: "absolute",
                    inset: "0",
                    width: "100%",
                    height: "100%",
                });
            }
        }
    }

    // === Drag and Drop ===

    private setupPaneDropTarget(pane: Pane): void {
        this.disposers.push(
            on(pane.el, "dragover", (ev) => {
                ev.preventDefault();
            }),
            on(pane.el, "pointerenter", () => {
                if (this.drag) {
                    this.drag.targetPane = pane;
                    const dropZone = pane.contentArea.querySelector(".dock-pane-dropzone") as HTMLElement;
                    if (dropZone) dropZone.style.display = "flex";
                }
            }),
            on(pane.el, "pointerleave", () => {
                if (this.drag && this.drag.targetPane === pane) {
                    this.drag.targetPane = null;
                    const dropZone = pane.contentArea.querySelector(".dock-pane-dropzone") as HTMLElement;
                    if (dropZone) dropZone.style.display = "none";
                }
            })
        );
    }

    beginDrag(widget: Widget, ev: PointerEvent): void {
        if (!this.widgets.has(widget.id)) return;

        const rect = widget.el.getBoundingClientRect();
        const ghost = el("div", { class: "widget-drag-ghost" });

        Object.assign(ghost.style, {
            position: "fixed",
            width: cssPx(200),
            height: cssPx(40),
            left: cssPx(ev.clientX - 100),
            top: cssPx(ev.clientY - 20),
            pointerEvents: "none",
            zIndex: "10000",
            opacity: "0.9",
            borderRadius: "4px",
            background: "var(--surface, #1a1a2e)",
            border: "2px solid var(--accent, #3b82f6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text, #fff)",
            fontSize: "12px",
            fontWeight: "600",
        });
        ghost.textContent = widget.getTitle();
        document.body.appendChild(ghost);

        this.drag = {
            widget,
            ghost,
            offsetX: 100,
            offsetY: 20,
            targetPane: null,
        };

        const onMove = (e: PointerEvent) => {
            if (!this.drag) return;
            this.drag.ghost.style.left = cssPx(e.clientX - this.drag.offsetX);
            this.drag.ghost.style.top = cssPx(e.clientY - this.drag.offsetY);
        };

        const onUp = () => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            this.endDrag();
        };

        window.addEventListener("pointermove", onMove, true);
        window.addEventListener("pointerup", onUp, true);
    }

    private endDrag(): void {
        if (!this.drag) return;

        const { widget, ghost, targetPane } = this.drag;
        ghost.remove();

        // Hide all drop zones
        for (const pane of this.panes.values()) {
            const dropZone = pane.contentArea.querySelector(".dock-pane-dropzone") as HTMLElement;
            if (dropZone) dropZone.style.display = "none";
        }

        if (targetPane) {
            this.addWidgetToPane(widget, targetPane);
        }

        this.drag = null;
    }

    beginResize(widget: Widget, ev: PointerEvent): void {
        // Pane resizing is handled by gutters, not widget resize handles
    }

    // === Template Picker ===

    getAvailableTemplates(): PaneLayoutTemplate[] {
        return DOCK_TEMPLATES;
    }

    getCurrentTemplate(): PaneLayoutTemplate | null {
        return this.currentTemplate;
    }

    // === Storage ===

    private storageKey(): string {
        return `dock-layout-${this.dashboard.id}`;
    }

    saveState(): void {
        const state: Record<string, { paneId: string; tabIndex: number }> = {};
        for (const [paneId, pane] of this.panes) {
            pane.widgets.forEach((widgetId, index) => {
                state[widgetId] = { paneId, tabIndex: index };
            });
        }
        storage.set(this.storageKey(), {
            widgets: state,
            templateId: this.currentTemplate?.id
        });
    }

    loadState(): void {
        const data = storage.get<{
            widgets: Record<string, { paneId: string; tabIndex: number }>;
            templateId?: string;
        }>(this.storageKey());
        if (data?.widgets) {
            (this as any).savedState = data;
        }
    }

    getSavedState(widgetId: string): { paneId: string; tabIndex: number } | null {
        const saved = (this as any).savedState?.widgets;
        return saved?.[widgetId] ?? null;
    }

    clearSavedState(): void {
        storage.remove(this.storageKey());
    }

    // === Lifecycle ===

    reset(): void {
        this.clearSavedState();
        if (this.currentTemplate) {
            this.applyTemplate(this.currentTemplate);
        }
    }

    destroy(): void {
        for (const d of this.disposers) d();
        this.disposers = [];
    }
}
