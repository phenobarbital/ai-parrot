// image-widget.ts - Widget that displays an image from a URL
import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";

export interface ImageWidgetOptions extends UrlWidgetOptions {
    alt?: string;
    objectFit?: "contain" | "cover" | "fill" | "none" | "scale-down";
}

/**
 * Widget that displays an image from a URL.
 */
export class ImageWidget extends UrlWidget {
    private _img: HTMLImageElement | undefined;
    private altText: string = "";
    private objectFit: string = "contain";

    constructor(opts: ImageWidgetOptions) {
        // Destructure image-specific options to avoid spreading them
        const { alt, objectFit, ...baseOpts } = opts;

        super({
            onRefresh: async () => this.updateContent(),  // Default refresh reloads image
            ...baseOpts,
            icon: opts.icon ?? "🖼️",
            title: opts.title || "Image",
        });
        this.altText = alt ?? opts.title ?? "Image";
        this.objectFit = objectFit ?? "contain";

        // Create element after constructor chain completes
        this.initializeElement();
    }

    private initializeElement(): void {
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

    protected override onInit(): void {
        // Do nothing here - element is created in constructor after super() returns
    }

    protected updateContent(): void {
        console.log("[ImageWidget] updateContent called, img:", !!this._img, "url:", this.url);
        if (this._img && this.url && this.url !== "undefined" && this.url !== "") {
            console.log("[ImageWidget] Setting img.src to:", this.url);
            this._img.src = this.url;
        }
    }

    /** Set alt text for the image */
    setAlt(text: string): void {
        this.altText = text;
        if (this._img) {
            this._img.alt = text;
        }
    }

    /** Set object-fit style */
    setObjectFit(fit: "contain" | "cover" | "fill" | "none" | "scale-down"): void {
        this.objectFit = fit;
        if (this._img) {
            this._img.style.objectFit = fit;
        }
    }
}
