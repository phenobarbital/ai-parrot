import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";
export interface IFrameWidgetOptions extends UrlWidgetOptions {
    sandbox?: string;
    allowFullscreen?: boolean;
}
/**
 * Widget that renders content from a URL in an iframe.
 */
export declare class IFrameWidget extends UrlWidget {
    private _iframe;
    private sandboxAttr;
    private allowFullscreen;
    constructor(opts: IFrameWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    protected updateContent(): void;
    /** Reload the iframe content from current URL */
    reload(): void;
}
//# sourceMappingURL=iframe-widget.d.ts.map