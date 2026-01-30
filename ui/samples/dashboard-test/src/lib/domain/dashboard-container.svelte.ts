import { DashboardTab, type DashboardTabConfig } from './dashboard-tab.svelte.js';
import { BasicChartWidget } from './basic-chart-widget.svelte.js';
import { TableWidget } from './table-widget.svelte.js';

export class DashboardContainer {
    // Reactive State - use an array for proper Svelte 5 reactivity
    // Map mutations don't trigger $state reactivity properly
    #tabsMap = new Map<string, DashboardTab>();
    #tabList = $state<DashboardTab[]>([]);
    activeTabId = $state<string | null>(null);

    // Sync helper - call after any Map mutation
    #syncTabList() {
        this.#tabList = Array.from(this.#tabsMap.values());
    }

    // Derived state
    get activeTab(): DashboardTab | null {
        return this.activeTabId ? this.#tabsMap.get(this.activeTabId) ?? null : null;
    }

    get tabList(): DashboardTab[] {
        return this.#tabList;
    }

    // For internal use - access the map directly
    get tabs(): Map<string, DashboardTab> {
        return this.#tabsMap;
    }

    // Domain Actions
    createTab(config: DashboardTabConfig): DashboardTab {
        const tab = new DashboardTab(config);
        this.#tabsMap.set(tab.id, tab);
        this.#syncTabList();

        // Auto-activate first tab
        if (!this.activeTabId) {
            this.activeTabId = tab.id;
        }

        console.log('[DashboardContainer] createTab:', tab.id, 'total:', this.#tabList.length);
        return tab;
    }

    removeTab(id: string): void {
        const tab = this.#tabsMap.get(id);
        if (!tab) return;

        tab.destroy();
        this.#tabsMap.delete(id);
        this.#syncTabList();

        // Switch to adjacent tab if active one was removed
        if (this.activeTabId === id) {
            this.activeTabId = this.#tabList[0]?.id ?? null;
        }

        console.log('[DashboardContainer] removeTab:', id, 'remaining:', this.#tabList.length);
    }

    activateTab(id: string): void {
        if (this.#tabsMap.has(id)) {
            this.activeTabId = id;
            console.log('[DashboardContainer] activateTab:', id);
        }
    }

    reorderTabs(fromIndex: number, toIndex: number): void {
        const entries = Array.from(this.#tabsMap.entries());
        const [moved] = entries.splice(fromIndex, 1);
        entries.splice(toIndex, 0, moved);
        this.#tabsMap = new Map(entries);
        this.#syncTabList();
    }

    createWidgetFromData(type: 'basic-chart' | 'table', data: unknown[]): void {
        const activeTab = this.activeTab;
        if (!activeTab) return;

        const dataStr = JSON.stringify(data, null, 2);
        const name = `New ${type === 'basic-chart' ? 'Chart' : 'Table'} (${new Date().toLocaleTimeString()})`;

        let newWidget;

        if (type === 'basic-chart') {
            newWidget = new BasicChartWidget({
                title: name,
                dataSourceType: 'json',
                jsonConfig: { mode: 'inline', json: dataStr }
            });
        } else {
            newWidget = new TableWidget({
                title: name,
                dataSourceType: 'json',
                jsonConfig: { mode: 'inline', json: dataStr }
            });
        }

        // Add to current layout
        activeTab.layout.addWidget(newWidget);
        console.log('[DashboardContainer] createWidgetFromData:', name);
    }
}

// Global Singleton for the application state
export const dashboardContainer = new DashboardContainer();
