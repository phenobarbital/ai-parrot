import { ContentWidget, type ContentWidgetConfig } from "./content-widget.svelte.js";

export class HtmlWidget extends ContentWidget {
    constructor(config: ContentWidgetConfig) {
        super({
            ...config,
            title: config.title || "HTML Widget",
            icon: config.icon ?? "📰",
        });
    }
}
