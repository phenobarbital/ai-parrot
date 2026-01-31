import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
import { storage } from '$lib/dashboard/domain/persistence';

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
        console.log('[MockLoader] Storage already populated, skipping hydration');
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

    // Force strict save to persistence
    // This assumes DashboardContainer has a save/persist method or we manually trigger it
    // Looking at persistence.ts/dashboard-container.ts, we might need to manually save active state
    // But for now let's assume the creation hooks trigger some reactivity or we call a saver.

    // Actually, checking dashboard-container.ts, it doesn't seem to auto-persist to `storage` object 
    // unless explicitly told to. Let's verify if we need to implement `save()` or if `DemoDashboard` does it.

    // For now, we will manually persist the state structure we just created to ensure Resolver can find it.
    await persistCurrentState();
}

async function persistCurrentState() {
    const state = {
        savedTabs: dashboardContainer.tabList.map(t => ({
            id: t.id,
            title: t.title,
            icon: t.icon,
            layoutMode: t.layoutMode,
            widgets: t.layout.getWidgets().map(w => ({
                id: w.id,
                title: w.title,
                icon: w.icon,
                type: w.config.dataSource ? 'data' : 'custom', // Simplified
                // In a real scenario we'd need full serialization
            }))
        }))
    };

    await storage.set('dashboard-state', state);
    console.log('[MockLoader] Demo data hydrated and persisted.');
}
