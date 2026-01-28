import type { Widget } from '../widget.svelte.js';
import type { DashboardTab } from '../dashboard-tab.svelte.js';
import type { LayoutEngine } from '../types.js';

// Abstract base class with common implementation
export abstract class LayoutBase implements LayoutEngine {
    readonly tab: DashboardTab;

    // Shared reactive state
    widgets = $state<Map<string, Widget>>(new Map());

    constructor(tab: DashboardTab) {
        this.tab = tab;
        // this.loadState(); // Call in subclass or manually
    }

    abstract addWidget(widget: Widget, placement?: unknown): void;
    abstract removeWidget(widget: Widget): void;
    abstract moveWidget(widget: Widget, placement: unknown): void;

    getWidgets(): Widget[] {
        return Array.from(this.widgets.values());
    }

    getWidgetIds(): string[] {
        return Array.from(this.widgets.keys());
    }

    getWidget(id: string): Widget | undefined {
        return this.widgets.get(id);
    }

    protected get storageKey(): string {
        return `layout-${this.tab.id}`;
    }

    abstract saveState(): void;
    abstract loadState(): void;
    abstract reset(): void;

    destroy(): void {
        this.saveState();
        // Use Array.from to avoid iterator issues during deletion
        for (const widget of Array.from(this.widgets.values())) {
            widget.destroy();
        }
        this.widgets.clear();
    }
}
