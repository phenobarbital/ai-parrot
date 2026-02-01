import { GridLayout } from './layouts/grid-layout.svelte.js';
import { DockLayout } from './layouts/dock-layout.svelte.js';
import { FreeLayout } from './layouts/free-layout.svelte.js';
import type { LayoutEngine, LayoutMode, DashboardTemplate, GridMode } from './types.js';
import type { ComponentName } from './component-registry.js';
import { Widget } from './widget.svelte.js';

export interface DashboardTabConfig {
    id?: string;
    title: string;
    icon?: string;
    layoutMode?: LayoutMode;
    gridMode?: GridMode;
    template?: DashboardTemplate;
    paneSize?: number;
    closable?: boolean;
    component?: ComponentName;  // Component name for 'component' layout mode
}

export class DashboardTab {
    readonly id: string;

    // Reactive State
    title = $state<string>('');
    icon = $state<string>('📊');
    layoutMode = $state<LayoutMode>('grid');
    gridMode = $state<GridMode>('flexible');
    closable = $state(true);
    component = $state<ComponentName | null>(null);  // Component name for 'component' layout mode

    // Template configuration
    template = $state<DashboardTemplate>('default');
    paneSize = $state<number>(300); // px width (left/right) or height (top/bottom)
    paneWidgets = $state<Widget[]>([]);

    // Layout engine (reactive reference)
    #layout = $state<LayoutEngine | null>(null);

    // Slideshow state
    slideshowState = $state<{
        active: boolean;
        index: number;
        widgets: string[];
        isPlaying: boolean;
        interval: number;
    }>({ active: false, index: 0, widgets: [], isPlaying: false, interval: 3000 });

    constructor(config: DashboardTabConfig) {
        this.id = config.id ?? crypto.randomUUID();
        this.title = config.title;
        this.icon = config.icon ?? '📊';
        this.layoutMode = config.layoutMode ?? 'grid';
        this.gridMode = config.gridMode ?? 'flexible';
        this.template = config.template ?? 'default';
        this.paneSize = config.paneSize ?? 300;
        this.closable = config.closable ?? true;
        this.component = config.component ?? null;

        // Only init layout for widget-based modes
        if (this.layoutMode !== 'component') {
            this.#initLayout();
        }
    }

    get layout(): LayoutEngine {
        // Force non-null assertion as it's initialized in constructor
        return this.#layout!;
    }

    #initLayout(): void {
        switch (this.layoutMode) {
            case 'free':
                this.#layout = new FreeLayout(this);
                break;
            case 'dock':
                this.#layout = new DockLayout(this);
                break;
            case 'grid':
            default:
                this.#layout = new GridLayout(this);
        }
    }

    // Switch layout mode preserving widgets
    switchLayout(mode: LayoutMode): void {
        if (mode === this.layoutMode) return;

        const widgets = this.layout.getWidgets();
        const oldLayout = this.layout;

        this.layoutMode = mode;
        this.#initLayout();

        // Transfer widgets to new layout
        for (const widget of widgets) {
            this.layout.addWidget(widget);
        }

        oldLayout.destroy();
    }

    // Slideshow
    enterSlideshow(): void {
        const widgetIds = this.layout.getWidgetIds();
        if (widgetIds.length === 0) return;

        this.slideshowState = {
            active: true,
            index: 0,
            widgets: widgetIds,
            isPlaying: false,
            interval: 5000
        };
    }

    exitSlideshow(): void {
        this.slideshowState = { active: false, index: 0, widgets: [], isPlaying: false, interval: 3000 };
    }

    slideshowNext(): void {
        if (!this.slideshowState.active) return;
        const len = this.slideshowState.widgets.length;
        this.slideshowState.index = (this.slideshowState.index + 1) % len;
    }

    slideshowPrev(): void {
        if (!this.slideshowState.active) return;
        const len = this.slideshowState.widgets.length;
        this.slideshowState.index = (this.slideshowState.index - 1 + len) % len;
    }

    toggleSlideshowPlay(): void {
        if (!this.slideshowState.active) return;
        this.slideshowState.isPlaying = !this.slideshowState.isPlaying;
    }

    setSlideshowInterval(ms: number): void {
        this.slideshowState.interval = ms;
    }

    // === Serialization ===
    toJSON(): DashboardTabConfig {
        // layout may be null for 'component' mode tabs
        const widgets = this.#layout?.getWidgets?.()?.map(w => w.toJSON()) ?? [];

        return {
            id: this.id,
            title: this.title,
            icon: this.icon,
            layoutMode: this.layoutMode,
            gridMode: this.gridMode,
            template: this.template,
            paneSize: this.paneSize,
            closable: this.closable,
            component: this.component ?? undefined
            // widgets are serialized separately by DashboardContainer.save()
        };
    }

    destroy(): void {
        this.#layout?.destroy();
    }
}
