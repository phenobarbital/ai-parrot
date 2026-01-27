import Dexie, { type Table } from 'dexie';
import { browser } from '$app/environment';

export interface DashboardData {
    id: string;
    title: string;
    icon: string;
    layoutMode: 'grid' | 'free' | 'dock';
    widgets: any[]; // Serialized widgets
    layoutData: any; // Serialized layout specific data
    updatedAt: number;
}

export class DashboardDatabase extends Dexie {
    dashboards!: Table<DashboardData, string>;

    constructor() {
        super('agentui_dashboard_workspace');
        this.version(1).stores({
            dashboards: 'id, title, updatedAt'
        });
    }
}

// Ensure unique instance, but only in browser
export const db = browser ? new DashboardDatabase() : ({} as DashboardDatabase);
