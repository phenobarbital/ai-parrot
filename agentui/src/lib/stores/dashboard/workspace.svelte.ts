import { Dashboard } from './dashboard.svelte';
import { v4 as uuidv4 } from 'uuid';
import { browser } from '$app/environment';

export class DashboardWorkspace {
    dashboards = $state<Dashboard[]>([]);
    activeDashboardId = $state<string | null>(null);
    isLoading = $state(true);

    constructor() {
        if (browser) {
            this.load();
        }
    }

    get activeDashboard() {
        return this.dashboards.find(d => d.id === this.activeDashboardId);
    }

    async addDashboard(title: string = "Dashboard", icon: string = "📊") {
        const id = uuidv4();
        const newDash = new Dashboard(id, title, icon);
        this.dashboards.push(newDash);

        await newDash.save();
        this.persistWorkspace();

        if (!this.activeDashboardId) {
            this.activeDashboardId = id;
        }
        return newDash;
    }

    async removeDashboard(id: string) {
        const idx = this.dashboards.findIndex(d => d.id === id);
        if (idx !== -1) {
            // Should also delete from DB? Yes.
            // await db.dashboards.delete(id); // TODO: Expose delete from Dashboard class or DB directly

            this.dashboards.splice(idx, 1);
            if (this.activeDashboardId === id) {
                this.activeDashboardId = this.dashboards.length > 0 ? this.dashboards[0].id : null;
            }
            this.persistWorkspace();
        }
    }

    activate(id: string) {
        if (this.dashboards.find(d => d.id === id)) {
            this.activeDashboardId = id;
            this.persistWorkspace(); // Save active state
        }
    }

    // Persist list of dashboard IDs and active one
    private persistWorkspace() {
        if (!browser) return;
        const data = {
            dashboardIds: this.dashboards.map(d => d.id),
            activeId: this.activeDashboardId
        };
        localStorage.setItem('agentui_dashboard_workspace', JSON.stringify(data));
    }

    async load() {
        if (!browser) return;
        this.isLoading = true;

        try {
            const raw = localStorage.getItem('agentui_dashboard_workspace');
            if (raw) {
                const data = JSON.parse(raw);
                const ids = data.dashboardIds || [];

                const loadedDashboards: Dashboard[] = [];
                for (const id of ids) {
                    const dash = await Dashboard.load(id);
                    if (dash) {
                        loadedDashboards.push(dash);
                    }
                }

                this.dashboards = loadedDashboards;
                this.activeDashboardId = data.activeId || (this.dashboards.length > 0 ? this.dashboards[0].id : null);
            }
        } catch (err) {
            console.error("Failed to load workspace", err);
        } finally {
            this.isLoading = false;
        }
    }
}

export const workspace = new DashboardWorkspace();
