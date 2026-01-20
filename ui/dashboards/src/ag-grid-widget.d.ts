import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
interface AgGridWidgetOptions extends WidgetOptions {
    gridOptions?: Record<string, unknown>;
}
export declare class AgGridWidget extends Widget {
    private _container;
    private _gridOptions;
    private _api;
    constructor(opts: AgGridWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    private loadResources;
    renderGrid(): Promise<void>;
    reload(): void;
}
export {};
//# sourceMappingURL=ag-grid-widget.d.ts.map