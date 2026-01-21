// iframe-widget.ts - Widget that displays a URL in an iframe
import { UrlWidget } from "./url-widget.js";
/**
 * Widget that renders content from a URL in an iframe.
 */
export class IFrameWidget extends UrlWidget {
    _iframe;
    sandboxAttr = "allow-scripts allow-same-origin";
    allowFullscreen = true;
    constructor(opts) {
        // Destructure iframe-specific options to avoid spreading them
        const { sandbox, allowFullscreen, ...baseOpts } = opts;
        super({
            onRefresh: async () => this.reload(), // Default refresh reloads iframe
            ...baseOpts,
            icon: opts.icon ?? "🌐",
            title: opts.title || "Web Content",
        });
        this.sandboxAttr = sandbox ?? "allow-scripts allow-same-origin";
        this.allowFullscreen = allowFullscreen ?? true;
        // Create element after constructor chain completes
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
        // Guard against string "undefined" (can happen from bad serialization)
        const sandbox = this.sandboxAttr && this.sandboxAttr !== "undefined"
            ? this.sandboxAttr
            : "allow-scripts allow-same-origin";
        this._iframe.setAttribute("sandbox", sandbox);
        if (this.allowFullscreen) {
            this._iframe.setAttribute("allowfullscreen", "");
        }
        this.setContent(this._iframe);
        // Update content if URL is already set
        if (this.url && this.url !== "undefined" && this.url !== "") {
            this.updateContent();
        }
    }
    onInit() {
        // Do nothing here - element is created in constructor after super() returns
    }
    updateContent() {
        console.log("[IFrameWidget] updateContent called, iframe:", !!this._iframe, "url:", this.url);
        if (this._iframe && this.url && this.url !== "undefined" && this.url !== "") {
            console.log("[IFrameWidget] Setting iframe.src to:", this.url);
            this._iframe.src = this.url;
        }
    }
    /** Reload the iframe content from current URL */
    reload() {
        console.log("[IFrameWidget] reload called, this.url:", this.url);
        if (!this._iframe)
            return;
        // Try DOM reload first (for same-origin iframes)
        try {
            if (this._iframe.contentDocument?.location) {
                this._iframe.contentDocument.location.reload();
                console.log("[IFrameWidget] reload via contentDocument.location.reload()");
                return;
            }
        }
        catch (e) {
            console.log("[IFrameWidget] contentDocument not accessible, falling back to src reset");
        }
        // Fallback: reset src to trigger reload
        if (this.url) {
            // Adding timestamp to bust cache
            const separator = this.url.includes("?") ? "&" : "?";
            this._iframe.src = `${this.url}${separator}_t=${Date.now()}`;
            console.log("[IFrameWidget] reload via src reset:", this._iframe.src);
        }
    }
}
//# sourceMappingURL=iframe-widget.js.map