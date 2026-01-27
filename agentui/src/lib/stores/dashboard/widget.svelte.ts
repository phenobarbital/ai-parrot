import { v4 as uuidv4 } from 'uuid';

export interface WidgetConfig {
    id?: string;
    title: string;
    type: string;
    [key: string]: any;
}

export interface WidgetPosition {
    x: number;
    y: number;
    w: number;
    h: number;
}

/**
 * Base Widget class using Svelte 5 Runes for reactivity.
 */
export class Widget {
    id: string;
    title: string = $state("");
    type: string;
    config: WidgetConfig;

    // Position state
    position: WidgetPosition = $state({ x: 0, y: 0, w: 4, h: 4 });

    // Data state
    data: any = $state(null);
    isLoading: boolean = $state(false);
    error: string | null = $state(null);

    // Layout state
    minimized: boolean = $state(false);
    maximized: boolean = $state(false);
    floating: boolean = $state(false);
    zIndex: number = $state(1);

    constructor(config: WidgetConfig) {
        this.id = config.id || uuidv4();
        this.title = config.title;
        this.type = config.type;
        this.config = config;

        // Initialize position if provided in config
        if (config.position) {
            this.position = config.position;
        }
    }

    /**
     * Load data - designed to be overridden or implemented by subclasses
     */
    async load(params: any = {}) {
        this.isLoading = true;
        this.error = null;
        try {
            // Base implementation can handle static data from config
            if (this.config.data) {
                this.data = this.config.data;
            }
            // Subclasses will call API here
        } catch (e: any) {
            this.error = e.message;
        } finally {
            this.isLoading = false;
        }
    }

    async refresh() {
        return this.load();
    }

    // specific actions for layout
    setPosition(x: number, y: number) {
        this.position.x = x;
        this.position.y = y;
    }

    setSize(w: number, h: number) {
        this.position.w = w;
        this.position.h = h;
    }

    toggleMinimize() {
        this.minimized = !this.minimized;
        // If maximizing, unminimize
        if (this.minimized && this.maximized) this.maximized = false;
    }

    toggleMaximize() {
        this.maximized = !this.maximized;
        if (this.maximized) {
            this.minimized = false;
            this.floating = true; // Maximize usually implies floating on top
            this.zIndex = 1000;
        } else {
            this.floating = false;
            this.zIndex = 1;
        }
    }

    setFloating(state: boolean) {
        this.floating = state;
        if (state) {
            this.zIndex = 100;
            // Initialize pixel dimensions if switching from grid (assume grid unit is small < 50)
            if (this.position.w < 50) this.position.w = this.position.w * 100;
            if (this.position.h < 50) this.position.h = this.position.h * 100;
            if (this.position.x < 50) this.position.x = this.position.x * 100 + 20; // Offset slightly
            if (this.position.y < 50) this.position.y = this.position.y * 100 + 20;
        } else {
            this.zIndex = 1;
            this.maximized = false;
            // Optionally revert to grid units?
            // For now, let's keep the pixels but next time it docks it might be huge.
            // Better to normalize back?
            // Let's assume the grid engine handles big numbers as 'span' which might be huge.
            // For MVP let's just reverse the operation roughly or reset to defaults if too big.
            if (this.position.w > 50) this.position.w = Math.max(1, Math.round(this.position.w / 100));
            if (this.position.h > 50) this.position.h = Math.max(1, Math.round(this.position.h / 100));
            // X/Y are mostly ignored by CSS grid auto-placement unless we explicitly set start/end lines.
            // Resetting X/Y to avoid huge grid gaps logic if we ever use manual grid placement.
            if (this.position.x > 50) this.position.x = 0;
            if (this.position.y > 50) this.position.y = 0;
        }
    }
}
