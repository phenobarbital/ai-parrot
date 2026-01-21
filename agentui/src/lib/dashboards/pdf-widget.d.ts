import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";
export interface PdfWidgetOptions extends UrlWidgetOptions {
    pdfOpenParams?: string;
}
/**
 * Widget that renders a PDF file from a URL in an iframe.
 */
export declare class PdfWidget extends UrlWidget {
    private _iframe;
    constructor(opts: PdfWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    protected updateContent(): void;
    /** Reload the iframe content */
    reload(): void;
}
//# sourceMappingURL=pdf-widget.d.ts.map