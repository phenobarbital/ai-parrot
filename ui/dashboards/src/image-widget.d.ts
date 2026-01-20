import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";
export interface ImageWidgetOptions extends UrlWidgetOptions {
    alt?: string;
    objectFit?: "contain" | "cover" | "fill" | "none" | "scale-down";
}
/**
 * Widget that displays an image from a URL.
 */
export declare class ImageWidget extends UrlWidget {
    private _img;
    private altText;
    private objectFit;
    constructor(opts: ImageWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    protected updateContent(): void;
    /** Set alt text for the image */
    setAlt(text: string): void;
    /** Set object-fit style */
    setObjectFit(fit: "contain" | "cover" | "fill" | "none" | "scale-down"): void;
}
//# sourceMappingURL=image-widget.d.ts.map