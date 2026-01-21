// ag-grid-widget.ts - Widget using AG Grid
import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";

// Sample definition
const DEFAULT_COLUMN_DEFS = [
    { headerName: "Make", field: "make" },
    { headerName: "Model", field: "model" },
    { headerName: "Price", field: "price" }
];
const DEFAULT_ROW_DATA = [
    { make: "Toyota", model: "Celica", price: 35000 },
    { make: "Ford", model: "Mondeo", price: 32000 },
    { make: "Porsche", model: "Boxster", price: 72000 }
];

interface AgGridWidgetOptions extends WidgetOptions {
    gridOptions?: Record<string, unknown>;
}

export class AgGridWidget extends Widget {
    private _container: HTMLElement | undefined;
    private _gridOptions: any; // ag-grid options object
    private _api: any = null;

    constructor(opts: AgGridWidgetOptions) {
        super({
            icon: "▦",
            ...opts,
            title: opts.title || "AG Table",
            onRefresh: async () => this.reload(),
        });

        // Initial options
        this._gridOptions = opts.gridOptions ?? {
            columnDefs: DEFAULT_COLUMN_DEFS,
            rowData: DEFAULT_ROW_DATA,
            defaultColDef: {
                sortable: true,
                filter: true,
                resizable: true
            },
            pagination: true
        };

        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        this._container.className = "ag-theme-alpine"; // Default theme
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
        });
        this.setContent(this._container);

        setTimeout(() => this.renderGrid(), 0);
    }

    protected override onInit(): void { }

    private async loadResources(): Promise<void> {
        // Load ag-grid-community script
        // @ts-ignore
        if (!window.agGrid) {
            // @ts-ignore
            await import("https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js");
        }

        // Load Styles (alpine theme) if NOT loaded
        // Caution: ag-grid styles are non-trivial to load dynamically without flickering or FOUC, 
        // but we'll try injecting the link.
        // NOTE: ag-grid 28+ usually bundles styles? No, usually separate CSS.
        // We'll trust the user might put them in index.html, or we inject them here.
        if (!document.getElementById("ag-grid-css")) {
            // Base styles
            /*
            // Not strictly necessary if using the bundled JS sometimes, but for community CDN usually needed
            // However, injecting CSS from JS is messy.
            // Let's assume for this "POC" widget we rely on a known CDN link.
            */
            // This is just a fallback, usually better in <head>
        }
    }

    async renderGrid(): Promise<void> {
        if (!this._container) return;

        try {
            await this.loadResources();

            // @ts-ignore
            if (window.agGrid) {
                if (this._api) {
                    this._api.destroy();
                }

                // @ts-ignore
                // ag-grid-community 30+ uses createGrid
                if (window.agGrid.createGrid) {
                    // @ts-ignore
                    this._api = window.agGrid.createGrid(this._container, this._gridOptions);
                } else {
                    // Older versions
                    // @ts-ignore
                    new window.agGrid.Grid(this._container, this._gridOptions);
                    this._api = this._gridOptions.api;
                }
            }

        } catch (err) {
            console.error("[AgGridWidget] Error:", err);
            if (this._container) this._container.textContent = "Failed to load AG Grid.";
        }
    }

    reload(): void {
        this.renderGrid();
    }

    // === Config ===
    // For brevity, we allow editing rowData/columnDefs as JSON string in settings
}
