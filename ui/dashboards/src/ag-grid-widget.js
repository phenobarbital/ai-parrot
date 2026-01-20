// ag-grid-widget.ts - Widget using AG Grid
import { Widget } from "./widget.js";
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
export class AgGridWidget extends Widget {
    _container;
    _gridOptions; // ag-grid options object
    _api = null;
    constructor(opts) {
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
    initializeElement() {
        this._container = document.createElement("div");
        this._container.className = "ag-theme-alpine"; // Default theme
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
        });
        this.setContent(this._container);
        setTimeout(() => this.renderGrid(), 0);
    }
    onInit() { }
    async loadResources() {
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
    async renderGrid() {
        if (!this._container)
            return;
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
                }
                else {
                    // Older versions
                    // @ts-ignore
                    new window.agGrid.Grid(this._container, this._gridOptions);
                    this._api = this._gridOptions.api;
                }
            }
        }
        catch (err) {
            console.error("[AgGridWidget] Error:", err);
            if (this._container)
                this._container.textContent = "Failed to load AG Grid.";
        }
    }
    reload() {
        this.renderGrid();
    }
}
//# sourceMappingURL=ag-grid-widget.js.map