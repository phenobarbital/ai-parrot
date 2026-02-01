import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
import { storage } from '$lib/dashboard/domain/persistence';
import type { DashboardTabConfig } from '$lib/dashboard/domain/dashboard-tab.svelte.js';
import { BasicChartWidget } from '$lib/dashboard/domain/basic-chart-widget.svelte.js';
import { TableWidget } from '$lib/dashboard/domain/table-widget.svelte.js';
import { MapWidget } from '$lib/dashboard/domain/map-widget.svelte.js';
import { MarkdownWidget } from '$lib/dashboard/domain/markdown-widget.svelte.js';
import { HtmlWidget } from '$lib/dashboard/domain/html-widget.svelte.js';
import { SimpleTableWidget } from '$lib/dashboard/domain/simple-table-widget.svelte.js';
import { ImageWidget } from '$lib/dashboard/domain/image-widget.svelte.js';
import { IFrameWidget } from '$lib/dashboard/domain/iframe-widget.svelte.js';

/**
 * Hydrates the dashboard container with mock data/demo dashboard
 * if the storage is empty.
 * 
 * This ensures that meaningful content is available when sharing links
 * are opened in a fresh session.
 */
export async function hydrateMockData(): Promise<void> {
    // Check if we have any tabs in storage
    const stored = await storage.get<{ savedTabs: any[] }>('dashboard-state');

    if (stored && stored.savedTabs && stored.savedTabs.length > 0) {
        console.log('[MockLoader] Storage found, hydrating from persistence...');
        await loadFromStorage(stored.savedTabs);
        return;
    }

    console.log('[MockLoader] Storage empty, hydrating with Demo Dashboard...');

    // Create the Demo Dashboard Tab
    const demoTab = dashboardContainer.createTab({
        title: 'Demo Dashboard',
        icon: 'mdi:view-dashboard',
        layoutMode: 'grid',
        gridMode: 'flexible'
    });

    // Populate with some default widgets for the demo
    // We recreate the structure found in DemoDashboard.svelte basically

    // 1. Sales Chart
    dashboardContainer.createWidgetFromData('basic-chart', [
        { month: 'Jan', sales: 4000 },
        { month: 'Feb', sales: 3000 },
        { month: 'Mar', sales: 2000 },
        { month: 'Apr', sales: 2780 },
        { month: 'May', sales: 1890 },
        { month: 'Jun', sales: 2390 },
    ]);

    // Rename the last created widget
    const salesWidget = demoTab.layout.widgets[demoTab.layout.widgets.length - 1];
    if (salesWidget) {
        salesWidget.title = 'Monthly Sales';
        salesWidget.icon = 'mdi:chart-bar';
    }

    // 2. Data Table
    dashboardContainer.createWidgetFromData('table', [
        { id: 1, name: 'John Doe', role: 'Admin', status: 'Active' },
        { id: 2, name: 'Jane Smith', role: 'User', status: 'Inactive' },
        { id: 3, name: 'Bob Johnson', role: 'Editor', status: 'Active' },
    ]);

    const tableWidget = demoTab.layout.widgets[demoTab.layout.widgets.length - 1];
    if (tableWidget) {
        tableWidget.title = 'User Directory';
        tableWidget.icon = 'mdi:account-group';
    }

    // Persist the initial demo state
    await persistCurrentState();
}

/**
 * Reconstructs the DashboardContainer state from stored data
 */
async function loadFromStorage(savedTabs: any[]) {
    // Clear existing (though usually empty on load)
    // dashboardContainer.clear(); // If such method existed

    for (const tabData of savedTabs) {
        // Check if tab already exists to avoid duplicates
        if (dashboardContainer.tabs.has(tabData.id)) continue;

        const config: DashboardTabConfig = {
            id: tabData.id,
            title: tabData.title,
            icon: tabData.icon,
            layoutMode: tabData.layoutMode,
            gridMode: tabData.gridMode,
            template: tabData.template,
            paneSize: tabData.paneSize,
            closable: tabData.closable,
            component: tabData.component
        };

        const tab = dashboardContainer.createTab(config);

        // Restore widgets
        if (tabData.widgets && Array.isArray(tabData.widgets)) {
            for (const widgetData of tabData.widgets) {
                try {
                    const widget = createWidgetFactory(widgetData.type, widgetData.config);
                    if (widget) {
                        tab.layout.addWidget(widget);
                    }
                } catch (e) {
                    console.error(`[MockLoader] Failed to restore widget ${widgetData.id}:`, e);
                }
            }
        }
    }
}

/**
 * Factory to create widget instances from type and config
 */
function createWidgetFactory(type: string, config: any) {
    if (!config) return null;

    switch (type) {
        case 'BasicChartWidget': return new BasicChartWidget(config);
        case 'TableWidget': return new TableWidget(config);
        case 'MapWidget': return new MapWidget(config);
        case 'MarkdownWidget': return new MarkdownWidget(config);
        case 'HtmlWidget': return new HtmlWidget(config);
        case 'SimpleTableWidget': return new SimpleTableWidget(config);
        case 'ImageWidget': return new ImageWidget(config);
        case 'IFrameWidget': return new IFrameWidget(config);
        // Add more types as needed
        default:
            console.warn(`[MockLoader] Unknown widget type: ${type}`);
            return null;
    }
}

/**
 * Persist the current state of DashboardContainer to storage.
 * Call this whenever the dashboard structure changes or is saved.
 */
export async function persistCurrentState() {
    const savedTabs = dashboardContainer.tabList.map(tab => {
        return {
            ...tab.toJSON(),
            widgets: tab.layout.getWidgets().map(w => {
                let type = 'Widget';
                if (w instanceof BasicChartWidget) type = 'BasicChartWidget';
                else if (w instanceof TableWidget) type = 'TableWidget';
                else if (w instanceof MapWidget) type = 'MapWidget';
                else if (w instanceof MarkdownWidget) type = 'MarkdownWidget';
                else if (w instanceof HtmlWidget) type = 'HtmlWidget';
                else if (w instanceof SimpleTableWidget) type = 'SimpleTableWidget';
                else if (w instanceof ImageWidget) type = 'ImageWidget';
                else if (w instanceof IFrameWidget) type = 'IFrameWidget';

                return {
                    id: w.id,
                    type: type,
                    config: w.toJSON()
                };
            })
        };
    });

    const state = { savedTabs };
    await storage.set('dashboard-state', state);
    console.log('[MockLoader] Dashboard state persisted.', { tabs: savedTabs.length });
}
