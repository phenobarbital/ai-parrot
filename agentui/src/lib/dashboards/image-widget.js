// image-widget.ts - Widget that displays an image from a URL
import { UrlWidget } from "./url-widget.js";
/**
 * Widget that displays an image from a URL.
 */
export class ImageWidget extends UrlWidget {
    _img;
    altText = "";
    objectFit = "contain";
    constructor(opts) {
        // Destructure image-specific options to avoid spreading them
        const { alt, objectFit, ...baseOpts } = opts;
        super({
            onRefresh: async () => this.updateContent(), // Default refresh reloads image
            ...baseOpts,
            icon: opts.icon ?? "🖼️",
            title: opts.title || "Image",
        });
        this.altText = alt ?? opts.title ?? "Image";
        this.objectFit = objectFit ?? "contain";
        // Create element after constructor chain completes
        this.initializeElement();
    }
    initializeElement() {
        this._img = document.createElement("img");
        Object.assign(this._img.style, {
            width: "100%",
            height: "100%",
            objectFit: this.objectFit,
            display: "block",
        });
        this._img.alt = this.altText;
        this.setContent(this._img);
        // Update content if URL is already set
        if (this.url && this.url !== "undefined" && this.url !== "") {
            this.updateContent();
        }
    }
    onInit() {
        // Do nothing here - element is created in constructor after super() returns
    }
    updateContent() {
        console.log("[ImageWidget] updateContent called, img:", !!this._img, "url:", this.url);
        if (this._img && this.url && this.url !== "undefined" && this.url !== "") {
            console.log("[ImageWidget] Setting img.src to:", this.url);
            this._img.src = this.url;
        }
    }
    /** Set alt text for the image */
    setAlt(text) {
        this.altText = text;
        if (this._img) {
            this._img.alt = text;
        }
    }
    /** Set object-fit style */
    setObjectFit(fit) {
        this.objectFit = fit;
        if (this._img) {
            this._img.style.objectFit = fit;
        }
    }
}
//# sourceMappingURL=image-widget.js.map