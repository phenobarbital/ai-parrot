import { ContentWidget, type ContentWidgetConfig } from "./content-widget.svelte.js";

export class MarkdownWidget extends ContentWidget {
    constructor(config: ContentWidgetConfig) {
        super({
            ...config,
            title: config.title || "Markdown Widget",
            icon: config.icon ?? "📝",
        });
    }
}
