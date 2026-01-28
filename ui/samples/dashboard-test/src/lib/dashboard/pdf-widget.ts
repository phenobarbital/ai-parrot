// pdf-widget.ts - Widget that displays a PDF file from a URL
import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";

export interface PdfWidgetOptions extends UrlWidgetOptions {
    pdfOpenParams?: string; // e.g., "page=1&zoom=100"
}

/**
 * Widget that renders a PDF file from a URL in an iframe.
 */
export class PdfWidget extends UrlWidget {
    private _iframe: HTMLIFrameElement | undefined;

    constructor(opts: PdfWidgetOptions) {
        super({
            ...opts,
            icon: opts.icon ?? "📄",
            title: opts.title || "PDF Document",
            onRefresh: async () => this.reload(),
        });

        this.initializeElement();
    }

    private initializeElement(): void {
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

    protected override onInit(): void {
        // Do nothing here - element is created in constructor
    }

    protected updateContent(): void {
        console.log("[PdfWidget] updateContent called, iframe:", !!this._iframe, "url:", this.url);
        if (this._iframe && this.url && this.url !== "undefined" && this.url !== "") {
            // Apply PDF open params if available? 
            // For now just basic URL
            console.log("[PdfWidget] Setting iframe.src to:", this.url);
            this._iframe.src = this.url;
        }
    }

    /** Reload the iframe content */
    reload(): void {
        if (!this._iframe) return;

        // Reload by resetting src (safest for cross-origin PDFs)
        if (this.url) {
            const separator = this.url.includes("?") ? "&" : "?";
            this._iframe.src = `${this.url}${separator}_t=${Date.now()}`;
        }
    }
}
