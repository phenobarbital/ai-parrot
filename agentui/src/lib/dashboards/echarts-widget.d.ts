import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
export interface EchartsWidgetOptions extends WidgetOptions {
    option?: Record<string, unknown>;
}
/**
 * Widget that renders Apache ECharts.
 */
export declare class EChartsWidget extends Widget {
    private _container;
    private _option;
    private _chart;
    private _resizeObserver;
    constructor(opts: EchartsWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    protected onDestroy(): void;
    renderChart(): Promise<void>;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createAdvancedTab;
}
//# sourceMappingURL=echarts-widget.d.ts.map