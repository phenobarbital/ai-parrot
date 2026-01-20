import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
interface MarkdownWidgetOptions extends WidgetOptions {
    content?: string;
}
/**
 * Widget that renders Markdown content.
 */
export declare class MarkdownWidget extends Widget {
    private _container;
    private _content;
    constructor(opts: MarkdownWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    renderMarkdown(): Promise<void>;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createContentTab;
}
export {};
//# sourceMappingURL=markdown-widget.d.ts.map