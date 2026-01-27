import { Widget } from './widget.svelte';
import { db } from './db';
import { v4 as uuidv4 } from 'uuid';

export type LayoutMode = 'grid' | 'free' | 'dock';

export interface GridConfig {
    cols: number;
    rowHeight: number;
    gap: number;
}

export class Dashboard {
    id: string;
    title = $state("New Dashboard");
    icon = $state("📊");
    layoutMode = $state<LayoutMode>("grid");

    // All widgets in this dashboard
    widgets = $state<Widget[]>([]);

    // Layout configuration
    gridConfig = $state<GridConfig>({ cols: 12, rowHeight: 100, gap: 16 });

    // Per-layout persistence state
    // We store layout-specific properties (x,y,w,h) in separate maps so switching layouts preserves state.
    // However, the Widget class itself mostly holds 'current' position.
    // To support "switching back restores prior layout", we need to snapshot positions when leaving a mode.
    savedLayouts = $state<Record<LayoutMode, any>>({
        grid: {},
        free: {},
        dock: {}
    });

    constructor(id: string, title?: string, icon?: string) {
        this.id = id;
        if (title) this.title = title;
        if (icon) this.icon = icon;
    }

    addWidget(widget: Widget) {
        this.widgets.push(widget);
        this.save();
    }

    removeWidget(id: string) {
        const idx = this.widgets.findIndex(w => w.id === id);
        if (idx !== -1) {
            this.widgets.splice(idx, 1);
            this.save();
        }
    }

    getWidget(id: string) {
        return this.widgets.find(w => w.id === id);
    }

    switchLayout(mode: LayoutMode) {
        // 1. Save current widget positions to savedLayouts[currentMode]
        this.snapshotLayout(this.layoutMode);

        // 2. Switch mode
        this.layoutMode = mode;

        // 3. Restore snapshot if exists
        this.restoreLayout(mode);

        this.save();
    }

    private snapshotLayout(mode: LayoutMode) {
        const snapshot: Record<string, any> = {};
        for (const w of this.widgets) {
            snapshot[w.id] = { ...w.position, zIndex: w.zIndex, floating: w.floating, maximized: w.maximized };
        }
        this.savedLayouts[mode] = snapshot;
    }

    private restoreLayout(mode: LayoutMode) {
        const snapshot = this.savedLayouts[mode];
        if (!snapshot) return; // First time entering this mode, keep default/current?

        // Or should we reset to default for that mode if no snapshot?
        // For now, let's try to apply what we have.
        for (const w of this.widgets) {
            const saved = snapshot[w.id];
            if (saved) {
                w.position = { ...saved }; // Restore x,y,w,h
                w.zIndex = saved.zIndex ?? 1;
                w.floating = saved.floating ?? false;
                w.maximized = saved.maximized ?? false;
            } else {
                // New widget added while in another mode?
                // It needs a default position for THIS mode.
                // We'll let the layout engine handle auto-placement or leave as is if compatible.
            }
        }
    }

    async save() {
        const data = {
            id: this.id,
            title: this.title,
            icon: this.icon,
            layoutMode: this.layoutMode,
            widgets: this.widgets.map(w => ({
                id: w.id,
                title: w.title,
                type: w.type,
                config: w.config,
                position: $state.snapshot(w.position), // Use snapshot to avoid proxy
                zIndex: w.zIndex,
                minimized: w.minimized,
                // ... other props
            })),
            layoutData: $state.snapshot(this.savedLayouts),
            updatedAt: Date.now()
        };
        await db.dashboards.put(data);
    }

    static async load(id: string): Promise<Dashboard | undefined> {
        const data = await db.dashboards.get(id);
        if (!data) return undefined;

        const dash = new Dashboard(data.id, data.title, data.icon);
        dash.layoutMode = data.layoutMode;
        if (data.layoutData) dash.savedLayouts = data.layoutData;

        // Rehydrate widgets
        if (data.widgets) {
            dash.widgets = data.widgets.map((w: any) => {
                const widget = new Widget(w.config || { title: w.title, type: w.type });
                widget.id = w.id;
                if (w.position) widget.position = w.position;
                widget.zIndex = w.zIndex ?? 1;
                widget.minimized = w.minimized ?? false;
                return widget;
            });
        }
        return dash;
    }
}
