// leaflet-widget.ts - Widget for rendering Leaflet maps
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
export class LeafletWidget extends Widget {
    private _container: HTMLElement | undefined;
    private _map: any = null;
    private _tileLayer: any = null;
    private _center: [number, number] = [51.505, -0.09];
    private _zoom: number = 13;

    constructor(opts: LeafletWidgetOptions) {
        super({
            icon: "🗺️",
            ...opts,
            title: opts.title || "Map",
            onRefresh: async () => this.reload(),
        });

        if (opts.center) this._center = opts.center;
        if (opts.zoom) this._zoom = opts.zoom;

        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            zIndex: "0", // Ensure map stays below other dashboards elements if needed
        });
        this.setContent(this._container);

        setTimeout(() => this.renderMap(), 0);
    }

    protected override onInit(): void { }

    protected override onDestroy(): void {
        if (this._map) {
            this._map.remove();
            this._map = null;
        }
    }

    // Leaflet requires CSS to be loaded
    private async loadLeafletResources(): Promise<void> {
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

    async renderMap(): Promise<void> {
        if (!this._container) return;

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
            } else {
                this._map.setView(this._center, this._zoom);
            }

        } catch (err) {
            console.error("[LeafletWidget] Error rendering map:", err);
        }
    }

    reload(): void {
        if (this._map) {
            this._map.setView(this._center, this._zoom);
            this._map.invalidateSize();
        } else {
            this.renderMap();
        }
    }

    // === Config ===

    override getConfigTabs(): ConfigTab[] {
        return [
            ...super.getConfigTabs(),
            this.createMapConfigTab()
        ];
    }

    protected override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);

        if (typeof config.zoom === "number") this._zoom = config.zoom;
        if (typeof config.lat === "number" && typeof config.lng === "number") {
            this._center = [config.lat, config.lng];
        }

        this.reload();
    }

    private createMapConfigTab(): ConfigTab {
        let latInput: HTMLInputElement;
        let lngInput: HTMLInputElement;
        let zoomInput: HTMLInputElement;

        return {
            id: "map",
            label: "Map Settings",
            icon: "📍",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                // Helper for inputs
                const createInput = (label: string, value: number, min?: number, max?: number) => {
                    const group = document.createElement("div");
                    Object.assign(group.style, { marginBottom: "12px" });

                    const lb = document.createElement("label");
                    lb.textContent = label;
                    Object.assign(lb.style, { display: "block", marginBottom: "4px", fontSize: "12px" });

                    const inp = document.createElement("input");
                    inp.type = "number";
                    inp.value = String(value);
                    if (min !== undefined) inp.min = String(min);
                    if (max !== undefined) inp.max = String(max);
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
