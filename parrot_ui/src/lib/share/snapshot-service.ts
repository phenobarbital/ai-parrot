import { dashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
import { storage } from '$lib/dashboard/domain/persistence';
import type { DashboardTab } from '$lib/dashboard/domain/dashboard-tab.svelte.js';
import { v4 as uuidv4 } from 'uuid';
import { BasicChartWidget } from '$lib/dashboard/domain/basic-chart-widget.svelte.js';
import { TableWidget } from '$lib/dashboard/domain/table-widget.svelte.js';
import { MapWidget } from '$lib/dashboard/domain/map-widget.svelte.js';
import { MarkdownWidget } from '$lib/dashboard/domain/markdown-widget.svelte.js';
import { HtmlWidget } from '$lib/dashboard/domain/html-widget.svelte.js';
import { SimpleTableWidget } from '$lib/dashboard/domain/simple-table-widget.svelte.js';
import { ImageWidget } from '$lib/dashboard/domain/image-widget.svelte.js';
import { IFrameWidget } from '$lib/dashboard/domain/iframe-widget.svelte.js';
import { VideoWidget } from '$lib/dashboard/domain/video-widget.svelte.js';
import { YouTubeWidget } from '$lib/dashboard/domain/youtube-widget.svelte.js';
import { VimeoWidget } from '$lib/dashboard/domain/vimeo-widget.svelte.js';
import { PdfWidget } from '$lib/dashboard/domain/pdf-widget.svelte.js';
import { Widget } from '$lib/dashboard/domain/widget.svelte.js';

export interface DashboardSnapshot {
    id: string;
    type: 'container' | 'tab' | 'widget';
    createdAt: number;
    data: any; // Serialized tab or array of tabs
}

const STORAGE_KEY = 'shared_snapshots';

export class SnapshotService {

    /**
     * Creates a snapshot of the current state for sharing.
     * @param tab Optional tab to share. If provided, shares only that tab. If null, shares entire container.
     */
    static async createSnapshot(tab?: DashboardTab): Promise<string> {
        const id = uuidv4();
        let snapshot: DashboardSnapshot;

        if (tab) {
            // Share single tab
            const layoutData = tab.layout?.serialize?.() ?? [];
            const serializedTab = {
                ...tab.toJSON(),
                widgets: layoutData
            };

            snapshot = {
                id,
                type: 'tab',
                createdAt: Date.now(),
                data: serializedTab
            };
        } else {
            // Share entire container
            const serializedTabs = dashboardContainer.tabList.map(t => {
                const layoutData = t.layout?.serialize?.() ?? [];
                return {
                    ...t.toJSON(),
                    widgets: layoutData
                };
            });

            snapshot = {
                id,
                type: 'container',
                createdAt: Date.now(),
                data: serializedTabs
            };
        }

        await this.saveSnapshot(snapshot);
        return id;
    }

    static async createWidgetSnapshot(widget: Widget): Promise<string> {
        const id = uuidv4();

        let type = 'Widget';
        if (widget instanceof BasicChartWidget) type = 'BasicChartWidget';
        else if (widget instanceof TableWidget) type = 'TableWidget';
        else if (widget instanceof MapWidget) type = 'MapWidget';
        else if (widget instanceof MarkdownWidget) type = 'MarkdownWidget';
        else if (widget instanceof HtmlWidget) type = 'HtmlWidget';
        else if (widget instanceof SimpleTableWidget) type = 'SimpleTableWidget';
        else if (widget instanceof ImageWidget) type = 'ImageWidget';
        else if (widget instanceof IFrameWidget) type = 'IFrameWidget';
        else if (widget instanceof VideoWidget) type = 'VideoWidget';
        else if (widget instanceof YouTubeWidget) type = 'YouTubeWidget';
        else if (widget instanceof VimeoWidget) type = 'VimeoWidget';
        else if (widget instanceof PdfWidget) type = 'PdfWidget';

        const snapshot: DashboardSnapshot = {
            id,
            type: 'widget',
            createdAt: Date.now(),
            data: {
                type,
                config: widget.toJSON()
            }
        };

        await this.saveSnapshot(snapshot);
        return id;
    }

    private static async saveSnapshot(snapshot: DashboardSnapshot) {
        let snapshots = await storage.get<DashboardSnapshot[]>(STORAGE_KEY) || [];
        snapshots.push(snapshot);
        await storage.set(STORAGE_KEY, snapshots);
    }

    /**
     * Retrieves a snapshot by ID
     */
    static async getSnapshot(id: string): Promise<DashboardSnapshot | undefined> {
        const snapshots = await storage.get<DashboardSnapshot[]>(STORAGE_KEY);
        return snapshots?.find(s => s.id === id);
    }
}
