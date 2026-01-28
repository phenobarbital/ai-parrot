import { type Snippet } from "svelte";

export interface WidgetOptions {
    id?: string;
    title?: string;
    icon?: string;
    x?: number;
    y?: number;
    w?: number;
    h?: number;
}

export class Widget {
    id: string;
    title = $state("New Widget");
    icon = $state("🧩");

    // Position & Size (Reactive)
    x = $state(0);
    y = $state(0);
    w = $state(300);
    h = $state(200);

    // State flags
    minimized = $state(false);
    maximized = $state(false);

    // Content Snippet (Lazy injection)
    content = $state<Snippet | null>(null);

    constructor(options: WidgetOptions = {}) {
        this.id = options.id ?? crypto.randomUUID();
        if (options.title) this.title = options.title;
        if (options.icon) this.icon = options.icon;
        if (options.x) this.x = options.x;
        if (options.y) this.y = options.y;
        if (options.w) this.w = options.w;
        if (options.h) this.h = options.h;
    }

    // Actions
    toggleMinimize() {
        this.minimized = !this.minimized;
    }

    toggleMaximize() {
        this.maximized = !this.maximized;
    }

    setContent(snippet: Snippet) {
        this.content = snippet;
    }

    moveTo(x: number, y: number) {
        this.x = x;
        this.y = y;
    }

    resize(w: number, h: number) {
        this.w = w;
        this.h = h;
    }
}
