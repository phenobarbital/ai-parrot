import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
export interface VegaWidgetOptions extends WidgetOptions {
    spec?: Record<string, unknown>;
}
/**
 * Widget that renders Vega/Vega-Lite charts using vega-embed.
 */
export declare class VegaWidget extends Widget {
    private _container;
    private _spec;
    private _view;
    constructor(opts: VegaWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    protected onDestroy(): void;
    renderChart(): Promise<void>;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createSpecConfigTab;
}
//# sourceMappingURL=vega-widget.d.ts.map