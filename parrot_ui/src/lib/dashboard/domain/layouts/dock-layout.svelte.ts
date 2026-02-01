/**
 * DockLayout - Pane-based layout with tabbed widgets
 * Domain layer - NO direct DOM manipulation
 */

import type { DashboardTab } from '../dashboard-tab.svelte.js';
import type { Widget } from '../widget.svelte.js';
import { LayoutBase } from './layout-base.svelte.js';
import { storageSync as storage } from '../persistence.js';

// === Types ===

export interface PaneStructure {
    type: 'row' | 'column' | 'pane';
    id?: string;
    children?: PaneStructure[];
    sizes?: number[];
}

export interface PaneLayoutTemplate {
    id: string;
    name: string;
    icon: string;
    structure: PaneStructure;
}

export interface Pane {
    id: string;
    widgetIds: string[];
    activeWidgetId: string | null;
}

export interface DockConfig {
    minPaneSize: number;
    gutterSize: number;
    initialTemplate?: string;
}

// === Predefined Templates ===

export const DOCK_TEMPLATES: PaneLayoutTemplate[] = [
    {
        id: '2-columns',
        name: 'Two Columns',
        icon: '▐▌',
        structure: {
            type: 'row',
            sizes: [50, 50],
            children: [
                { type: 'pane', id: 'left' },
                { type: 'pane', id: 'right' }
            ]
        }
    },
    {
        id: '3-columns',
        name: 'Three Columns',
        icon: '▐█▌',
        structure: {
            type: 'row',
            sizes: [33, 34, 33],
            children: [
                { type: 'pane', id: 'left' },
                { type: 'pane', id: 'center' },
                { type: 'pane', id: 'right' }
            ]
        }
    },
    {
        id: 'sidebar-right',
        name: 'Sidebar Right',
        icon: '█▐',
        structure: {
            type: 'row',
            sizes: [70, 30],
            children: [
                { type: 'pane', id: 'main' },
                { type: 'pane', id: 'sidebar' }
            ]
        }
    },
    {
        id: 'holy-grail',
        name: 'Holy Grail',
        icon: '▄█▄',
        structure: {
            type: 'column',
            sizes: [20, 60, 20],
            children: [
                { type: 'pane', id: 'header' },
                {
                    type: 'row',
                    sizes: [25, 50, 25],
                    children: [
                        { type: 'pane', id: 'left' },
                        { type: 'pane', id: 'main' },
                        { type: 'pane', id: 'right' }
                    ]
                },
                { type: 'pane', id: 'footer' }
            ]
        }
    }
];

// === DockLayout Class ===

export class DockLayout extends LayoutBase {
    // Configuration
    config = $state<DockConfig>({
        minPaneSize: 100,
        gutterSize: 6,
        initialTemplate: '2-columns'
    });

    // Template and pane structure
    currentTemplate = $state<PaneLayoutTemplate | null>(null);
    panes = $state<Map<string, Pane>>(new Map());

    // Pane sizes for resize - Map<containerId, number[]>
    paneSizes = $state<Map<string, number[]>>(new Map());

    // Drag state for moving widgets between panes
    dragState = $state<{
        active: boolean;
        widgetId: string | null;
        sourcePane: string | null;
        targetPane: string | null;
    }>({ active: false, widgetId: null, sourcePane: null, targetPane: null });

    // Gutter resize state
    resizeState = $state<{
        active: boolean;
        containerId: string | null;
        gutterIndex: number;
        startSizes: number[];
        startPosition: number;
    } | null>(null);

    constructor(tab: DashboardTab, config?: Partial<DockConfig>) {
        super(tab);
        if (config) {
            this.config = { ...this.config, ...config };
        }

        // Apply initial template
        const templateId = this.config.initialTemplate ?? '2-columns';
        const template = DOCK_TEMPLATES.find(t => t.id === templateId) ?? DOCK_TEMPLATES[0];
        this.applyTemplate(template);
    }

    // === Derived Getters ===

    get paneList(): Pane[] {
        return Array.from(this.panes.values());
    }

    get paneIds(): string[] {
        return Array.from(this.panes.keys());
    }

    getPane(id: string): Pane | undefined {
        return this.panes.get(id);
    }

    getPaneWidgets(paneId: string): Widget[] {
        const pane = this.panes.get(paneId);
        if (!pane) return [];
        return pane.widgetIds
            .map(id => this.widgets.get(id))
            .filter((w): w is Widget => w !== undefined);
    }

    getActiveWidgetForPane(paneId: string): Widget | undefined {
        const pane = this.panes.get(paneId);
        if (!pane?.activeWidgetId) return undefined;
        return this.widgets.get(pane.activeWidgetId);
    }

    // === Template Management ===

    applyTemplate(template: PaneLayoutTemplate): void {
        // Save existing widgets to redistribute
        const existingWidgets = this.getWidgets();

        // Clear current panes
        this.panes.clear();
        this.paneSizes.clear();
        this.currentTemplate = template;

        // Build panes from structure
        this.#buildPanesFromStructure(template.structure);

        // Redistribute existing widgets among new panes
        if (existingWidgets.length > 0) {
            const paneIds = this.paneIds;
            existingWidgets.forEach((widget, index) => {
                const targetPaneId = paneIds[index % paneIds.length];
                this.#addWidgetToPane(widget, targetPaneId);
            });
        }

        this.saveState();
    }

    #buildPanesFromStructure(structure: PaneStructure, containerId: string = 'root'): void {
        if (structure.type === 'pane') {
            const paneId = structure.id ?? containerId;
            this.panes.set(paneId, {
                id: paneId,
                widgetIds: [],
                activeWidgetId: null
            });
            return;
        }

        // Row or Column - store sizes
        const resolvedContainerId = structure.id ?? containerId;
        if (structure.children && structure.sizes) {
            this.paneSizes.set(resolvedContainerId, [...structure.sizes]);
        }

        // Process children recursively
        structure.children?.forEach((child, index) => {
            const childId = child.id ?? `${resolvedContainerId}-${index}`;
            this.#buildPanesFromStructure(child, childId);
        });
    }

    // === Widget Management ===

    addWidget(widget: Widget, paneIdOrPosition?: string): void {
        // If no pane specified, use first available
        const paneId = typeof paneIdOrPosition === 'string'
            ? paneIdOrPosition
            : this.paneIds[0];

        if (!paneId || !this.panes.has(paneId)) {
            console.warn(`[DockLayout] Invalid pane: ${paneId}`);
            return;
        }

        // Register in base layout
        this.widgets.set(widget.id, widget);

        // Add to pane
        this.#addWidgetToPane(widget, paneId);

        // Notify widget
        widget.attach(this.tab, { paneId });
        this.panes = new Map(this.panes); // Force reactivity
        this.saveState();
    }

    #addWidgetToPane(widget: Widget, paneId: string): void {
        const pane = this.panes.get(paneId);
        if (!pane) return;

        // Create new pane object for immutability
        const newPane = { ...pane };
        let modified = false;

        // Add to pane's widget array
        if (!newPane.widgetIds.includes(widget.id)) {
            newPane.widgetIds = [...newPane.widgetIds, widget.id];
            modified = true;
        }

        // Activate if first widget
        if (!newPane.activeWidgetId) {
            newPane.activeWidgetId = widget.id;
            modified = true;
        }

        if (modified) {
            this.panes.set(paneId, newPane);
        }
    }

    removeWidget(widget: Widget): void {
        // Find and remove from pane
        for (const [paneId, pane] of this.panes) {
            if (pane.widgetIds.includes(widget.id)) {
                const newPane = { ...pane };
                newPane.widgetIds = newPane.widgetIds.filter(id => id !== widget.id);

                // If it was active, activate another
                if (newPane.activeWidgetId === widget.id) {
                    newPane.activeWidgetId = newPane.widgetIds[0] ?? null;
                }
                this.panes.set(paneId, newPane);
                break;
            }
        }

        // Remove from global registry
        this.widgets.delete(widget.id);
        widget.detach();
        this.panes = new Map(this.panes); // Force reactivity
        this.saveState();
    }

    moveWidget(widget: Widget, targetPaneId: string): void {
        if (!this.panes.has(targetPaneId)) return;

        // Remove from current pane
        for (const [paneId, pane] of this.panes) {
            if (pane.widgetIds.includes(widget.id)) {
                const newPane = { ...pane };
                newPane.widgetIds = newPane.widgetIds.filter(id => id !== widget.id);
                if (newPane.activeWidgetId === widget.id) {
                    newPane.activeWidgetId = newPane.widgetIds[0] ?? null;
                }
                this.panes.set(paneId, newPane);
                break;
            }
        }

        // Add to new pane
        this.#addWidgetToPane(widget, targetPaneId);
        widget.updatePlacement({ paneId: targetPaneId });
        this.panes = new Map(this.panes); // Force reactivity
        this.saveState();
    }

    // === Tab Activation ===

    activateWidgetInPane(paneId: string, widgetId: string): void {
        const pane = this.panes.get(paneId);
        if (!pane || !pane.widgetIds.includes(widgetId)) return;
        if (pane.activeWidgetId === widgetId) return;

        this.panes.set(paneId, { ...pane, activeWidgetId: widgetId });
        this.panes = new Map(this.panes); // Force reactivity
        this.saveState();
    }

    // === Drag & Drop ===

    startWidgetDrag(widgetId: string, sourcePaneId: string): void {
        this.dragState = {
            active: true,
            widgetId,
            sourcePane: sourcePaneId,
            targetPane: null
        };
    }

    updateDragTarget(paneId: string | null): void {
        if (!this.dragState.active) return;
        this.dragState.targetPane = paneId;
    }

    endWidgetDrag(): void {
        if (!this.dragState.active) return;

        const { widgetId, sourcePane, targetPane } = this.dragState;

        if (widgetId && targetPane && targetPane !== sourcePane) {
            const widget = this.widgets.get(widgetId);
            if (widget) {
                this.moveWidget(widget, targetPane);
            }
        }

        this.dragState = { active: false, widgetId: null, sourcePane: null, targetPane: null };
    }

    cancelWidgetDrag(): void {
        this.dragState = { active: false, widgetId: null, sourcePane: null, targetPane: null };
    }

    // === Gutter Resize ===

    startGutterResize(containerId: string, gutterIndex: number, startPosition: number): void {
        const sizes = this.paneSizes.get(containerId);
        if (!sizes) return;

        this.resizeState = {
            active: true,
            containerId,
            gutterIndex,
            startSizes: [...sizes],
            startPosition
        };
    }

    updateGutterResize(currentPosition: number, containerSize: number): void {
        if (!this.resizeState?.active) return;

        const { containerId, gutterIndex, startSizes, startPosition } = this.resizeState;
        const delta = currentPosition - startPosition;
        const deltaPercent = (delta / containerSize) * 100;

        const newSizes = [...startSizes];

        // Redistribute between the two adjacent panels
        const leftIndex = gutterIndex;
        const rightIndex = gutterIndex + 1;

        const pairTotal = startSizes[leftIndex] + startSizes[rightIndex];
        const minPercent = Math.max(1, (this.config.minPaneSize / containerSize) * 100);
        const safeMin = Math.min(minPercent, pairTotal / 2);
        const left = Math.min(
            pairTotal - safeMin,
            Math.max(safeMin, startSizes[leftIndex] + deltaPercent)
        );
        const right = pairTotal - left;

        newSizes[leftIndex] = left;
        newSizes[rightIndex] = right;

        this.paneSizes.set(containerId!, newSizes);
        this.paneSizes = new Map(this.paneSizes); // Force reactivity
    }

    endGutterResize(): void {
        this.resizeState = null;
        this.saveState();
    }

    // === Pane Operations ===

    // === Pane Operations ===

    splitPane(paneId: string, direction: 'horizontal' | 'vertical'): void {
        const pane = this.panes.get(paneId);
        if (!pane || !this.currentTemplate) return;

        // Create new pane
        const newPaneId = `pane-${crypto.randomUUID().slice(0, 8)}`;
        this.panes.set(newPaneId, {
            id: newPaneId,
            widgetIds: [],
            activeWidgetId: null
        });

        // Update structure
        const parentInfo = this.#findParent(this.currentTemplate.structure, paneId);

        if (parentInfo) {
            // Case 1: Pane is inside a container (row/column)
            const { parent, index } = parentInfo;

            // Create a new container to hold both panes
            const newContainerId = `container-${crypto.randomUUID().slice(0, 8)}`;
            const newStructure: PaneStructure = {
                type: direction === 'horizontal' ? 'row' : 'column',
                id: newContainerId,
                sizes: [50, 50],
                children: [
                    { type: 'pane', id: paneId },
                    { type: 'pane', id: newPaneId }
                ]
            };

            // Replace old pane with new container
            if (parent.children) {
                parent.children[index] = newStructure;

                // Initialize sizes for new container
                this.paneSizes.set(newContainerId, [50, 50]);
            }
        } else if (this.currentTemplate.structure.id === paneId) {
            // Case 2: Root is the pane
            const newContainerId = `container-${crypto.randomUUID().slice(0, 8)}`;
            const oldStructure = { ...this.currentTemplate.structure };

            this.currentTemplate.structure = {
                type: direction === 'horizontal' ? 'row' : 'column',
                id: newContainerId,
                sizes: [50, 50], // Start with equal split
                children: [
                    oldStructure,
                    { type: 'pane', id: newPaneId }
                ]
            };
            this.paneSizes.set(newContainerId, [50, 50]);
        }

        // Force reactivity update
        this.currentTemplate = { ...this.currentTemplate };
        this.saveState();
    }

    closePane(paneId: string): void {
        const pane = this.panes.get(paneId);
        if (!pane || !this.currentTemplate) return;

        // Move widgets to another pane before closing
        // Find a suitable target pane (sibling or just first available)
        const allPanes = this.paneIds.filter(id => id !== paneId);
        if (allPanes.length > 0 && pane.widgetIds.length > 0) {
            // Try to find a sibling
            const parentInfo = this.#findParent(this.currentTemplate.structure, paneId);
            let targetPaneId = allPanes[0];

            if (parentInfo && parentInfo.parent.children) {
                const sibling = parentInfo.parent.children.find(c => c.id !== paneId && c.type === 'pane');
                if (sibling && sibling.id) {
                    targetPaneId = sibling.id;
                }
            }

            for (const widgetId of [...pane.widgetIds]) {
                const widget = this.widgets.get(widgetId);
                if (widget) {
                    this.moveWidget(widget, targetPaneId);
                }
            }
        }

        // Update structure
        const parentInfo = this.#findParent(this.currentTemplate.structure, paneId);

        if (parentInfo) {
            const { parent, index } = parentInfo;

            if (parent.children && parent.children.length > 1) {
                // Remove pane from children
                parent.children.splice(index, 1);

                // Redistribute sizes
                // If we have sizes for this container, remove the corresponding size
                if (parent.id && this.paneSizes.has(parent.id)) {
                    const sizes = this.paneSizes.get(parent.id)!;
                    if (sizes.length > index) {
                        // Distribute the closed pane's size to neighbor
                        const sizeToRemove = sizes[index];
                        sizes.splice(index, 1);

                        // Add to previous or next
                        if (index > 0) {
                            sizes[index - 1] += sizeToRemove;
                        } else if (sizes.length > 0) {
                            sizes[0] += sizeToRemove;
                        }

                        this.paneSizes.set(parent.id, [...sizes]);
                    }
                }

                // Collapse parent if only 1 child remains
                if (parent.children.length === 1) {
                    const remainingChild = parent.children[0];
                    // Verify if we can simplify structure?
                    // For now, let's keep it simple. If we collapse, we need to replace 'parent' in ITS parent.
                    // This requires recursive 'collapse' logic which is complex.
                    // A simpler approach: if 1 child, just let it take 100% space? 
                    // But we likely want to remove the intermediate row/col.

                    // Let's implement full collapse later if needed. 
                    // For now, just remove the child is enough for functionality.
                }
            } else {
                // Parent becomes empty? Should not happen if we maintain structure.
                // If root was a row and we close one pane, the other pane should become root.
            }

            // Handle Root Collapse: if structure is root and we removed a child
            if (this.currentTemplate.structure === parent && parent.children!.length === 1) {
                this.currentTemplate.structure = parent.children![0];
            }
        }

        this.panes.delete(paneId);
        // Force reactivity update
        this.currentTemplate = { ...this.currentTemplate };
        this.paneSizes = new Map(this.paneSizes); // Force reactivity
        this.saveState();
    }

    // Helper to find parent of a node
    #findParent(node: PaneStructure, targetId: string): { parent: PaneStructure, index: number } | null {
        if (!node.children) return null;

        for (let i = 0; i < node.children.length; i++) {
            const child = node.children[i];
            if (child.id === targetId || (child.type === 'pane' && child.id === targetId)) {
                return { parent: node, index: i };
            }

            const found = this.#findParent(child, targetId);
            if (found) return found;
        }
        return null;
    }

    // === Persistence ===

    protected override get storageKey(): string {
        return `dock-layout-${this.tab.id}`;
    }

    saveState(): void {
        const state = {
            templateId: this.currentTemplate?.id,
            panes: Object.fromEntries(
                Array.from(this.panes.entries()).map(([id, pane]) => [
                    id,
                    { widgetIds: pane.widgetIds, activeWidgetId: pane.activeWidgetId }
                ])
            ),
            paneSizes: Object.fromEntries(this.paneSizes)
        };
        storage.set(this.storageKey, state);
    }

    loadState(): void {
        const state = storage.get<{
            templateId?: string;
            panes?: Record<string, { widgetIds: string[]; activeWidgetId: string | null }>;
            paneSizes?: Record<string, number[]>;
        }>(this.storageKey);

        if (state?.templateId) {
            const template = DOCK_TEMPLATES.find(t => t.id === state.templateId);
            if (template) {
                this.currentTemplate = template;
            }
        }

        if (state?.paneSizes) {
            this.paneSizes = new Map(Object.entries(state.paneSizes));
        }
    }

    serialize(): unknown {
        // DockLayout
        return Array.from(this.widgets.values()).map(w => w.toJSON());
    }

    reset(): void {
        storage.remove(this.storageKey);

        const template = DOCK_TEMPLATES.find(t => t.id === '2-columns') ?? DOCK_TEMPLATES[0];
        this.applyTemplate(template);
    }
}
