import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
export interface UrlWidgetOptions extends WidgetOptions {
    url?: string | undefined;
}
/**
 * Abstract base class for widgets that display content from a URL.
 * Subclasses: IFrameWidget, ImageWidget
 */
export declare abstract class UrlWidget extends Widget {
    protected url: string;
    constructor(opts: UrlWidgetOptions);
    /** Set the URL and update content */
    setUrl(url: string): void;
    /** Get current URL */
    getUrl(): string;
    /** Abstract: Subclasses implement how URL is rendered */
    protected abstract updateContent(): void;
    /** Override to add URL config tab */
    getConfigTabs(): ConfigTab[];
    /** Apply URL config on save */
    protected onConfigSave(config: Record<string, unknown>): void;
    /** Create the URL configuration tab */
    protected createUrlConfigTab(): ConfigTab;
}
//# sourceMappingURL=url-widget.d.ts.map