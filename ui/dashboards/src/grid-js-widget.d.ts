import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
interface GridJsWidgetOptions extends WidgetOptions {
    columns?: string[];
    data?: any[][];
}
export declare class GridJsWidget extends Widget {
    private _container;
    private _grid;
    private _columns;
    private _data;
    constructor(opts: GridJsWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    private loadResources;
    renderGrid(): Promise<void>;
}
export {};
//# sourceMappingURL=grid-js-widget.d.ts.map