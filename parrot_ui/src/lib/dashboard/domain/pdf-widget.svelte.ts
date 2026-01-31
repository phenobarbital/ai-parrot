import { UrlManagedWidget, type UrlManagedConfig } from "./url-managed-widget.svelte.js";

export class PdfWidget extends UrlManagedWidget {
    constructor(config: UrlManagedConfig) {
        super({
            ...config,
            title: config.title || "PDF Viewer",
            icon: config.icon ?? "📄",
        });
    }

    getPdfUrl(): string {
        return this.getResolvedSource();
    }
}
