import { ApiWidget, type ApiWidgetOptions } from "./api-widget.js";
import type { ConfigTab } from "./widget-config-modal.js";
export type TotalType = "sum" | "avg" | "median" | "none";
export interface ColumnConfig {
    key: string;
    label?: string;
    mask?: "money" | "number" | "percent" | string;
    hidden?: boolean;
}
export interface SimpleTableWidgetOptions extends ApiWidgetOptions {
    /** Enable zebra striping (default: true) */
    zebra?: boolean;
    /** Calculate totals for numeric columns */
    totals?: TotalType;
    /** Column configurations */
    columns?: ColumnConfig[];
}
export declare class SimpleTableWidget extends ApiWidget {
    private _zebra;
    private _totals;
    private _columns;
    private _tableContainer;
    constructor(opts: SimpleTableWidgetOptions);
    private initializeTableContainer;
    protected renderData(): void;
    private calculateTotal;
    private formatValue;
    private humanize;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createTableConfigTab;
    private createFormGroup;
    private styleInput;
}
//# sourceMappingURL=simple-table-widget.d.ts.map