import { Widget } from './widget.svelte';
import { v4 as uuidv4 } from 'uuid';

export interface GridConfig {
    cols: number;
    rowHeight: number;
    gap: number;
}

export type LayoutMode = 'grid' | 'free' | 'dock';

export class DashboardModel {
    id: string;
    title: string = $state("New Dashboard");
    icon: string = $state("📊");
    layoutMode: LayoutMode = $state("grid");

    widgets: Widget[] = $state([]);
    gridConfig: GridConfig = $state({ cols: 12, rowHeight: 100, gap: 16 });

    constructor(id: string, title?: string, icon?: string) {
        this.id = id;
        if (title) this.title = title;
        if (icon) this.icon = icon;
    }

    addWidget(widget: Widget) {
        // Basic auto-placement logic for grid mode
        if (this.layoutMode === 'grid') {
            const maxY = this.widgets.reduce((max, w) => Math.max(max, w.position.y + w.position.h), 0);
            if (!widget.position.y && maxY > 0) {
                widget.position.y = maxY;
            }
        }
        this.widgets.push(widget);
    }

    removeWidget(id: string) {
        const idx = this.widgets.findIndex(w => w.id === id);
        if (idx !== -1) {
            this.widgets.splice(idx, 1);
        }
    }

    getWidget(id: string) {
        return this.widgets.find(w => w.id === id);
    }
}

export class DashboardContainerStore {
    dashboards: DashboardModel[] = $state([]);
    activeId: string | null = $state(null);

    constructor() {
        // Initialize with one dashboard by default if needed, or empty
    }

    get activeDashboard() {
        return this.dashboards.find(d => d.id === this.activeId);
    }

    addDashboard(title: string = "Dashboard", icon: string = "📊") {
        const id = uuidv4();
        const newDash = new DashboardModel(id, title, icon);
        this.dashboards.push(newDash);
        if (!this.activeId) {
            this.activeId = id;
        }
        return newDash;
    }

    removeDashboard(id: string) {
        const idx = this.dashboards.findIndex(d => d.id === id);
        if (idx !== -1) {
            this.dashboards.splice(idx, 1);
            if (this.activeId === id) {
                this.activeId = this.dashboards.length > 0 ? this.dashboards[0].id : null;
            }
        }
    }

    activate(id: string) {
        if (this.dashboards.find(d => d.id === id)) {
            this.activeId = id;
        }
    }
}

export function createDashboardContainerStore() {
    return new DashboardContainerStore();
}
