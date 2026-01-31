/**
 * Dashboard store wrapper - bridges old import paths to new dashboard library.
 * Re-exports DashboardContainer as DashboardModel for AgentDashboard.svelte compatibility.
 */
import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
import type { DashboardTab } from '$lib/dashboard/domain/dashboard-tab.svelte.js';
import type { Widget } from '$lib/dashboard/domain/widget.svelte.js';

/**
 * DashboardModel wrapper class for AgentDashboard.svelte compatibility.
 * The old AgentDashboard expects a model with addWidget/getWidget methods.
 */
export class DashboardModel {
    id: string;
    title: string;
    icon: string;
    tab: DashboardTab | null = null;

    constructor(id: string, title: string, icon: string) {
        this.id = id;
        this.title = title;
        this.icon = icon;

        // Create a tab for this "model" if none exists
        if (dashboardContainer.tabList.length === 0) {
            this.tab = dashboardContainer.createTab({
                title: title,
                icon: icon,
                layoutMode: 'grid'
            });
            dashboardContainer.activateTab(this.tab.id);
        } else {
            this.tab = dashboardContainer.activeTab;
        }
    }

    get widgets(): Widget[] {
        return this.tab?.layout.widgets ?? [];
    }

    set widgets(value: Widget[]) {
        // Clear all widgets from the layout
        if (this.tab?.layout) {
            const current = [...this.tab.layout.widgets];
            for (const w of current) {
                this.tab.layout.removeWidget(w);
            }
        }
    }

    addWidget(widget: Widget): void {
        if (this.tab?.layout) {
            this.tab.layout.addWidget(widget);
        }
    }

    getWidget(id: string): Widget | undefined {
        return this.widgets.find(w => w.id === id);
    }

    removeWidget(widget: Widget): void {
        if (this.tab?.layout) {
            this.tab.layout.removeWidget(widget);
        }
    }
}
