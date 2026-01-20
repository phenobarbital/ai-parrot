// leaflet-widget.ts - Widget for rendering Leaflet maps
import { Widget } from "./widget.js";
/**
 * Widget that renders a Leaflet map.
 */
export class LeafletWidget extends Widget {
    _container;
    _map = null;
    _tileLayer = null;
    _center = [51.505, -0.09];
    _zoom = 13;
    constructor(opts) {
        super({
            icon: "🗺️",
            ...opts,
            title: opts.title || "Map",
            onRefresh: async () => this.reload(),
        });
        if (opts.center)
            this._center = opts.center;
        if (opts.zoom)
            this._zoom = opts.zoom;
        this.initializeElement();
    }
    initializeElement() {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            zIndex: "0", // Ensure map stays below other dashboards elements if needed
        });
        this.setContent(this._container);
        setTimeout(() => this.renderMap(), 0);
    }
    onInit() { }
    onDestroy() {
        if (this._map) {
            this._map.remove();
            this._map = null;
        }
    }
    // Leaflet requires CSS to be loaded
    async loadLeafletResources() {
        if (!document.getElementById("leaflet-css")) {
            const link = document.createElement("link");
            link.id = "leaflet-css";
            link.rel = "stylesheet";
            link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
            document.head.appendChild(link);
        }
        // @ts-ignore
        if (!window.L) {
            // @ts-ignore
            await import("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js");
        }
    }
    async renderMap() {
        if (!this._container)
            return;
        try {
            await this.loadLeafletResources();
            // @ts-ignore
            const L = window.L;
            if (!this._map) {
                this._map = L.map(this._container).setView(this._center, this._zoom);
                this._tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 19,
                    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                }).addTo(this._map);
                // Add a sample marker
                L.marker(this._center).addTo(this._map)
                    .bindPopup('A pretty CSS3 popup.<br> Easily customizable.')
                    .openPopup();
                // Handle resize
                const resizeObserver = new ResizeObserver(() => {
                    this._map?.invalidateSize();
                });
                resizeObserver.observe(this._container);
            }
            else {
                this._map.setView(this._center, this._zoom);
            }
        }
        catch (err) {
            console.error("[LeafletWidget] Error rendering map:", err);
        }
    }
    reload() {
        if (this._map) {
            this._map.setView(this._center, this._zoom);
            this._map.invalidateSize();
        }
        else {
            this.renderMap();
        }
    }
    // === Config ===
    getConfigTabs() {
        return [
            ...super.getConfigTabs(),
            this.createMapConfigTab()
        ];
    }
    onConfigSave(config) {
        super.onConfigSave(config);
        if (typeof config.zoom === "number")
            this._zoom = config.zoom;
        if (typeof config.lat === "number" && typeof config.lng === "number") {
            this._center = [config.lat, config.lng];
        }
        this.reload();
    }
    createMapConfigTab() {
        let latInput;
        let lngInput;
        let zoomInput;
        return {
            id: "map",
            label: "Map Settings",
            icon: "📍",
            render: (container) => {
                container.innerHTML = "";
                // Helper for inputs
                const createInput = (label, value, min, max) => {
                    const group = document.createElement("div");
                    Object.assign(group.style, { marginBottom: "12px" });
                    const lb = document.createElement("label");
                    lb.textContent = label;
                    Object.assign(lb.style, { display: "block", marginBottom: "4px", fontSize: "12px" });
                    const inp = document.createElement("input");
                    inp.type = "number";
                    inp.value = String(value);
                    if (min !== undefined)
                        inp.min = String(min);
                    if (max !== undefined)
                        inp.max = String(max);
                    Object.assign(inp.style, {
                        width: "100%", padding: "6px", borderRadius: "4px", border: "1px solid #ccc", boxSizing: "border-box"
                    });
                    group.appendChild(lb);
                    group.appendChild(inp);
                    container.appendChild(group);
                    return inp;
                };
                latInput = createInput("Latitude", this._center[0], -90, 90);
                lngInput = createInput("Longitude", this._center[1], -180, 180);
                zoomInput = createInput("Zoom Level", this._zoom, 0, 19);
            },
            save: () => ({
                lat: parseFloat(latInput.value),
                lng: parseFloat(lngInput.value),
                zoom: parseInt(zoomInput.value, 10),
            })
        };
    }
}
//# sourceMappingURL=leaflet-widget.js.map