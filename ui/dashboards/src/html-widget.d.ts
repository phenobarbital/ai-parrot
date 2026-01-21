import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
interface HTMLWidgetOptions extends WidgetOptions {
    content?: string;
}
/**
 * Widget that renders HTML content.
 */
export declare class HTMLWidget extends Widget {
    private _container;
    private _content;
    constructor(opts: HTMLWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    renderHTML(): Promise<void>;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createContentTab;
}
export {};
//# sourceMappingURL=html-widget.d.ts.map