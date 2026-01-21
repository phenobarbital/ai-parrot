// pdf-widget.ts - Widget that displays a PDF file from a URL
import { UrlWidget } from "./url-widget.js";
/**
 * Widget that renders a PDF file from a URL in an iframe.
 */
export class PdfWidget extends UrlWidget {
    _iframe;
    constructor(opts) {
        super({
            ...opts,
            icon: opts.icon ?? "📄",
            title: opts.title || "PDF Document",
            onRefresh: async () => this.reload(),
        });
        this.initializeElement();
    }
    initializeElement() {
        this._iframe = document.createElement("iframe");
        Object.assign(this._iframe.style, {
            width: "100%",
            height: "100%",
            border: "none",
            display: "block",
        });
        // Use standard PDF viewer handling (browser default)
        // No special sandbox needed specifically for PDFs usually, but good to have reasonable defaults
        // if we were to restrict it. For now, standard iframe behavior.
        this.setContent(this._iframe);
        // Update content if URL is already set
        if (this.url && this.url !== "undefined" && this.url !== "") {
            this.updateContent();
        }
    }
    onInit() {
        // Do nothing here - element is created in constructor
    }
    updateContent() {
        console.log("[PdfWidget] updateContent called, iframe:", !!this._iframe, "url:", this.url);
        if (this._iframe && this.url && this.url !== "undefined" && this.url !== "") {
            // Apply PDF open params if available? 
            // For now just basic URL
            console.log("[PdfWidget] Setting iframe.src to:", this.url);
            this._iframe.src = this.url;
        }
    }
    /** Reload the iframe content */
    reload() {
        if (!this._iframe)
            return;
        // Reload by resetting src (safest for cross-origin PDFs)
        if (this.url) {
            const separator = this.url.includes("?") ? "&" : "?";
            this._iframe.src = `${this.url}${separator}_t=${Date.now()}`;
        }
    }
}
//# sourceMappingURL=pdf-widget.js.map