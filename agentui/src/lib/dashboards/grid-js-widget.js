// grid-js-widget.ts - Widget using Grid.js
import { Widget } from "./widget.js";
const DEFAULT_COLS = ["Name", "Email", "Phone Number"];
const DEFAULT_DATA = [
    ["John", "john@example.com", "(353) 01 222 3333"],
    ["Mark", "mark@gmail.com", "(01) 22 888 4444"],
    ["Eoin", "eoin@gmail.com", "0097 22 654 00033"],
    ["Sarah", "sarahcdd@gmail.com", "+322 876 1233"],
    ["Afshin", "afshin@mail.com", "(353) 22 87 8356"]
];
export class GridJsWidget extends Widget {
    _container;
    _grid = null;
    _columns = DEFAULT_COLS;
    _data = DEFAULT_DATA;
    constructor(opts) {
        super({
            icon: "📅", // Calendar/Table-ish icon
            ...opts,
            title: opts.title || "Grid.js Table",
            onRefresh: async () => this.renderGrid(),
        });
        if (opts.columns)
            this._columns = opts.columns;
        if (opts.data)
            this._data = opts.data;
        this.initializeElement();
    }
    initializeElement() {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%", // Grid.js handles scrolling inside
            overflow: "auto"
        });
        this.setContent(this._container);
        setTimeout(() => this.renderGrid(), 0);
    }
    onInit() { }
    async loadResources() {
        if (!document.getElementById("gridjs-css")) {
            const link = document.createElement("link");
            link.id = "gridjs-css";
            link.rel = "stylesheet";
            link.href = "https://unpkg.com/gridjs/dist/theme/mermaid.min.css";
            document.head.appendChild(link);
        }
        // @ts-ignore
        if (!window.gridjs) {
            // @ts-ignore
            await import("https://unpkg.com/gridjs/dist/gridjs.umd.js");
        }
    }
    async renderGrid() {
        if (!this._container)
            return;
        try {
            await this.loadResources();
            // @ts-ignore
            const { Grid } = window.gridjs;
            if (this._grid) {
                // Determine if we destroy and recreate or update
                // Grid.js update is slightly complex; simple re-render for now
                this._container.innerHTML = "";
            }
            this._grid = new Grid({
                columns: this._columns,
                data: this._data,
                pagination: true,
                search: true,
                sort: true,
                resizable: true
            }).render(this._container);
        }
        catch (err) {
            console.error("[GridJsWidget] Error:", err);
        }
    }
}
//# sourceMappingURL=grid-js-widget.js.map