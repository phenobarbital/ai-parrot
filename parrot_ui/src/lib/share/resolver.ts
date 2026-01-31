import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
import { storage } from '$lib/dashboard/domain/persistence';
import type { DashboardTab } from '$lib/dashboard/domain/dashboard-tab.svelte.js';
import type { Widget } from '$lib/dashboard/domain/widget.svelte.js';
import type { Module } from '$lib/types';
import { mockClients } from '$lib/data/mock-data';

/**
 * Resolver Service
 * Locates objects by ID across memory and storage.
 */

// === Dashboard & Tab Resolution ===

export async function resolveDashboard(id: string): Promise<DashboardTab | undefined> {
    // 1. Check active memory
    const inMemory = dashboardContainer.tabs.get(id);
    if (inMemory) return inMemory;

    // 2. Check storage (and potentially re-hydrate)
    // Note: In this architecture, "Dashboard" is currently synonymous with "DashboardTab" 
    // or a grouping of tabs. Since DashboardContainer holds tabs, we look for a Tab with this ID
    // that effectively acts as a Dashboard.

    // We might need to ensure the container is loaded.
    // If not found in memory, we assume it's missing or not loaded.
    // Real implementation would try to load from backend/storage if not present.

    return undefined;
}

export async function resolveTab(tabId: string): Promise<DashboardTab | undefined> {
    // In our current domain model, DashboardContainer manages Tabs directly.
    return dashboardContainer.tabs.get(tabId);
}

// === Widget Resolution ===

export async function resolveWidget(widgetId: string): Promise<Widget | undefined> {
    // Scan all tabs to find the widget
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
