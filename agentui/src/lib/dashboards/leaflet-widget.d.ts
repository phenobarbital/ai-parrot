import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
interface LeafletWidgetOptions extends WidgetOptions {
    center?: [number, number];
    zoom?: number;
}
/**
 * Widget that renders a Leaflet map.
 */
export declare class LeafletWidget extends Widget {
    private _container;
    private _map;
    private _tileLayer;
    private _center;
    private _zoom;
    private _mapReady;
    constructor(opts: LeafletWidgetOptions);
    private initializeElement;
    protected onInit(): void;
    protected onDestroy(): void;
    private loadLeafletResources;
    renderMap(): Promise<void>;
    reload(): void;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    private createMapConfigTab;
}
export {};
//# sourceMappingURL=leaflet-widget.d.ts.map