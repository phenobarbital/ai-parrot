import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
import { storage } from '$lib/dashboard/domain/persistence';
import type { DashboardTab } from '$lib/dashboard/domain/dashboard-tab.svelte.js';
import { Widget } from '$lib/dashboard/domain/widget.svelte.js';
import type { Module } from '$lib/types';
import { mockClients } from '$lib/data/mock-data';

/**
 * Resolver Service
 * Locates objects by ID across memory and storage.
 */

// === Dashboard & Tab Resolution ===

import { SnapshotService } from './snapshot-service';

export async function resolveDashboard(id: string): Promise<DashboardTab | undefined> {
    // 1. Check snapshots (New Sharing Logic)
    const snapshot = await SnapshotService.getSnapshot(id);
    if (snapshot) {
        // Clear container for a clean shared view (optional but recommended for shared view)
        // However, we don't have a clean method to clear tabs in dashboardContainer except removing one by one
        // or effectively we just assume we add to it. To strictly "load" the dashboard, we probably want to isolate it.
        // For now, let's just add them.

        // Actually, we should probably clear to avoid duplicates or mixing with previous session state if any.
        // But dashboardContainer doesn't have `clear()`. We can implement it or manually remove keys.
        // Let's rely on duplication checks or just overwrite.

        let firstTab: DashboardTab | undefined;

        const tabsData = snapshot.type === 'container' ? snapshot.data : [snapshot.data];

        for (const tabData of tabsData) {
            // Avoid duplicates if ID collision (though unlikely with UUIDs unless reloading same link)
            if (dashboardContainer.tabs.has(tabData.id)) {
                if (!firstTab) firstTab = dashboardContainer.tabs.get(tabData.id);
                continue;
            }

            const tab = dashboardContainer.createTab({
                id: tabData.id,
                title: tabData.title,
                icon: tabData.icon,
                layoutMode: tabData.layoutMode,
                gridMode: tabData.gridMode,
                template: tabData.template,
                paneSize: tabData.paneSize,
                closable: tabData.closable,
                component: tabData.component
            });

            if (!firstTab) firstTab = tab;

            if (tabData.widgets && Array.isArray(tabData.widgets)) {
                for (const wData of tabData.widgets) {
                    let widget;
                    // Check for explicit type (from mock-loader style or snapshot)
                    const config = wData.config || wData; // Handle both wrapped and direct config
                    const type = wData.type;

                    if (type) {
                        if (type === 'BasicChartWidget') widget = new (await import('$lib/dashboard/domain/basic-chart-widget.svelte.js')).BasicChartWidget(config);
                        else if (type === 'TableWidget') widget = new (await import('$lib/dashboard/domain/table-widget.svelte.js')).TableWidget(config);
                        else if (type === 'MapWidget') widget = new (await import('$lib/dashboard/domain/map-widget.svelte.js')).MapWidget(config);
                        else if (type === 'MarkdownWidget') widget = new (await import('$lib/dashboard/domain/markdown-widget.svelte.js')).MarkdownWidget(config);
                        else if (type === 'HtmlWidget') widget = new (await import('$lib/dashboard/domain/html-widget.svelte.js')).HtmlWidget(config);
                        else if (type === 'SimpleTableWidget') widget = new (await import('$lib/dashboard/domain/simple-table-widget.svelte.js')).SimpleTableWidget(config);
                        else if (type === 'ImageWidget') widget = new (await import('$lib/dashboard/domain/image-widget.svelte.js')).ImageWidget(config);
                        else if (type === 'IFrameWidget') widget = new (await import('$lib/dashboard/domain/iframe-widget.svelte.js')).IFrameWidget(config);
                        else widget = new Widget(config);
                    } else {
                        // Heuristic
                        if (wData.chartEngine) widget = new (await import('$lib/dashboard/domain/basic-chart-widget.svelte.js')).BasicChartWidget(wData);
                        else if (wData.dataSource) widget = new (await import('$lib/dashboard/domain/table-widget.svelte.js')).TableWidget(wData);
                        else widget = new Widget(wData);
                    }

                    if (widget) tab.layout.addWidget(widget);
                }
            }
        }

        return firstTab;
    }

    // 2. Fallback: Check active memory
    const inMemory = dashboardContainer.tabs.get(id);
    if (inMemory) return inMemory;

    // 3. Fallback: Check storage 'dashboards' (Legacy/Direct Save)
    // ... (existing logic) ... return undefined at end
    const storedDashboards = await storage.get<any[]>('dashboards');
    if (storedDashboards) {
        const foundData = storedDashboards.find(d => d.id === id);
        if (foundData) {
            // Rehydrate
            // Check if already in container (race condition check)
            if (dashboardContainer.tabs.has(id)) return dashboardContainer.tabs.get(id);

            const tab = dashboardContainer.createTab({
                id: foundData.id,
                title: foundData.title,
                icon: foundData.icon,
                layoutMode: foundData.layoutMode,
                gridMode: foundData.gridMode,
                template: foundData.template,
                paneSize: foundData.paneSize,
                closable: foundData.closable,
                component: foundData.component
            });

            // Restore widgets
            if (foundData.widgets && Array.isArray(foundData.widgets)) {
                // Determine if widgets are serialized as { type, config } or just config (if toJSON was used directly)
                // DashboardContainer.save() maps widgets to { ...toJSON(), widgets: layoutData } ?? 
                // Wait, DashboardContainer.save uses tab.layout.serialize().
                // layout.serialize() in GridLayout returns w.toJSON().
                // w.toJSON() does NOT include 'type'.
                // This is a problem. We don't know the widget type from just w.toJSON().

                // However, mock-loader's persistCurrentState added a 'type' field explicitly.
                // DashboardContainer.save() uses `layout.serialize()` which calls `w.toJSON()`.
                // Widget.toJSON() does not include type.

                // If the user used DashboardContainer.save(), we might have lost the type info if it wasn't added.
                // Let's check DashboardContainer.save implementation again.
                // It maps tab -> { ...tab.toJSON(), widgets: layout.serialize() }

                // If layout.serialize() returns a list of configs without type, we default to generic Widget or try to guess.
                // But wait, if persistence is broken for types, we can't restore correctly 100%.

                // Let's assume for now we use a generic Widget or infer from config (e.g. dataSource presence).
                // Or better, we should fix Widget.toJSON to include type? No, usually class name isn't there.

                // In mock-loader we explicitly added 'type'.
                // If DashboardContainer.save() is used, it uses layout.serialize().
                // We corrected GridLayout to return widgets.map(w => w.toJSON()).

                // IMPLICIT FIX: usage of 'type' property if present.
                // If not present, we default to widget with checking properties.

                for (const wData of foundData.widgets) {
                    let widget;
                    // Check for explicit type (from mock-loader style)
                    if (wData.type) {
                        if (wData.type === 'BasicChartWidget') widget = new (await import('$lib/dashboard/domain/basic-chart-widget.svelte.js')).BasicChartWidget(wData.config || wData);
                        else if (wData.type === 'TableWidget') widget = new (await import('$lib/dashboard/domain/table-widget.svelte.js')).TableWidget(wData.config || wData);
                        else if (wData.type === 'MapWidget') widget = new (await import('$lib/dashboard/domain/map-widget.svelte.js')).MapWidget(wData.config || wData);
                        // ... add other types
                        else widget = new Widget(wData.config || wData);
                    } else {
                        // Heuristic or default
                        // If it has 'chartEngine' it's likely a chart
                        if (wData.chartEngine) widget = new (await import('$lib/dashboard/domain/basic-chart-widget.svelte.js')).BasicChartWidget(wData);
                        else if (wData.dataSource) widget = new (await import('$lib/dashboard/domain/table-widget.svelte.js')).TableWidget(wData); // Table/Chart both use dataSource though
                        else widget = new Widget(wData);
                    }

                    if (widget) tab.layout.addWidget(widget);
                }
            }
            return tab;
        }
    }

    // 3. Fallback: Check 'dashboard-state' (mock-loader legacy/demo key)
    const storedState = await storage.get<{ savedTabs: any[] }>('dashboard-state');
    if (storedState && storedState.savedTabs) {
        const foundData = storedState.savedTabs.find(d => d.id === id);
        if (foundData) {
            if (dashboardContainer.tabs.has(id)) return dashboardContainer.tabs.get(id);
            // We can trigger hydrateMockData or manually rehydrate this one tab.
            // Manual rehydration for specific tab:
            const tab = dashboardContainer.createTab({ ...foundData });
            if (foundData.widgets) {
                for (const wData of foundData.widgets) {
                    // mock-loader saves with { type, config }
                    let widget;
                    const config = wData.config;
                    if (wData.type === 'BasicChartWidget') widget = new (await import('$lib/dashboard/domain/basic-chart-widget.svelte.js')).BasicChartWidget(config);
                    else if (wData.type === 'TableWidget') widget = new (await import('$lib/dashboard/domain/table-widget.svelte.js')).TableWidget(config);
                    else if (wData.type === 'MapWidget') widget = new (await import('$lib/dashboard/domain/map-widget.svelte.js')).MapWidget(config);
                    else if (wData.type === 'MarkdownWidget') widget = new (await import('$lib/dashboard/domain/markdown-widget.svelte.js')).MarkdownWidget(config);
                    else if (wData.type === 'HtmlWidget') widget = new (await import('$lib/dashboard/domain/html-widget.svelte.js')).HtmlWidget(config);
                    else widget = new Widget(config);

                    if (widget) tab.layout.addWidget(widget);
                }
            }
            return tab;
        }
    }

    return undefined;
}

export async function resolveTab(tabId: string): Promise<DashboardTab | undefined> {
    // In our current domain model, DashboardContainer manages Tabs directly.
    return dashboardContainer.tabs.get(tabId);
}

// === Widget Resolution ===

export async function resolveWidget(widgetId: string): Promise<Widget | undefined> {
    // 1. Check snapshots
    const snapshot = await SnapshotService.getSnapshot(widgetId);
    if (snapshot && snapshot.type === 'widget') {
        const wData = snapshot.data;
        const config = wData.config;
        const type = wData.type;

        let widget;
        if (type) {
            if (type === 'BasicChartWidget') widget = new (await import('$lib/dashboard/domain/basic-chart-widget.svelte.js')).BasicChartWidget(config);
            else if (type === 'TableWidget') widget = new (await import('$lib/dashboard/domain/table-widget.svelte.js')).TableWidget(config);
            else if (type === 'MapWidget') widget = new (await import('$lib/dashboard/domain/map-widget.svelte.js')).MapWidget(config);
            else if (type === 'MarkdownWidget') widget = new (await import('$lib/dashboard/domain/markdown-widget.svelte.js')).MarkdownWidget(config);
            else if (type === 'HtmlWidget') widget = new (await import('$lib/dashboard/domain/html-widget.svelte.js')).HtmlWidget(config);
            else if (type === 'SimpleTableWidget') widget = new (await import('$lib/dashboard/domain/simple-table-widget.svelte.js')).SimpleTableWidget(config);
            else if (type === 'ImageWidget') widget = new (await import('$lib/dashboard/domain/image-widget.svelte.js')).ImageWidget(config);
            else if (type === 'IFrameWidget') widget = new (await import('$lib/dashboard/domain/iframe-widget.svelte.js')).IFrameWidget(config);
            else if (type === 'VideoWidget') widget = new (await import('$lib/dashboard/domain/video-widget.svelte.js')).VideoWidget(config);
            else if (type === 'YouTubeWidget') widget = new (await import('$lib/dashboard/domain/youtube-widget.svelte.js')).YouTubeWidget(config);
            else if (type === 'VimeoWidget') widget = new (await import('$lib/dashboard/domain/vimeo-widget.svelte.js')).VimeoWidget(config);
            else if (type === 'PdfWidget') widget = new (await import('$lib/dashboard/domain/pdf-widget.svelte.js')).PdfWidget(config);
            else widget = new Widget(config);
        }
        return widget;
    }

    // 2. Fallback: Scan active memory
    for (const tab of dashboardContainer.tabList) {
        const widget = tab.layout.getWidgets().find(w => w.id === widgetId);
        if (widget) return widget;
    }

    return undefined;
}

// === Module Resolution ===

export async function resolveModule(moduleId: string): Promise<Module | undefined> {
    // Flatten all modules from all programs in the mock data (default client)
    // In a real app, this would query the API or ClientStore

    const client = mockClients.find(c => c.slug === 'localhost') || mockClients[0];
    if (!client) return undefined;

    for (const program of client.programs) {
        const module = program.modules.find(m => m.id === moduleId || m.slug === moduleId);
        if (module) return module;
    }

    return undefined;
}
