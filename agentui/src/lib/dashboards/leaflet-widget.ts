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
    private _mapReady = false;

    constructor(opts: LeafletWidgetOptions) {
        super({
            icon: "🗺️",
            ...opts,
            title: opts.title || "Map",
            onRefresh: async () => this.reload(),
        });

        if (opts.center) this._center = opts.center;
        if (opts.zoom) this._zoom = opts.zoom;

        // Initialize element immediately
        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            zIndex: "0",
            minHeight: "100px" // Ensure at least some height
        });

        // CRITICAL FIX: Leaflet needs the container to have size.
        // The default widget-content has padding which constrains 100% height children.
        // We must override the content section styles.
        if (this.contentSection) {
            Object.assign(this.contentSection.style, {
                padding: "0",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden" // Prevent scrollbars
            });
        }

        this.setContent(this._container);

        // Defer rendering
        setTimeout(() => this.renderMap(), 100);
    }

    protected override onInit(): void {
        // Double check styles in case they were overwritten
        if (this.contentSection) {
            Object.assign(this.contentSection.style, {
                padding: "0",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden"
            });
        }
    }

    protected override onDestroy(): void {
        if (this._map) {
            this._map.remove();
            this._map = null;
        }
        this._mapReady = false;
    }

    // Leaflet requires CSS to be loaded and Script to be globally available
    private async loadLeafletResources(): Promise<void> {
        // 1. Load CSS
        if (!document.getElementById("leaflet-css")) {
            const link = document.createElement("link");
            link.id = "leaflet-css";
            link.rel = "stylesheet";
            link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
            document.head.appendChild(link);
        }

        // 2. Load JS (UMD)
        // Check if L is already available
        // @ts-ignore
        if (window.L) return;

        return new Promise((resolve, reject) => {
            // Check if script tags is already present but L not yet ready
            const existingScript = document.getElementById("leaflet-js");
            if (existingScript) {
                existingScript.addEventListener("load", () => resolve());
                existingScript.addEventListener("error", () => reject(new Error("Failed to load Leaflet script")));
                return;
            }

            const script = document.createElement("script");
            script.id = "leaflet-js";
            script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
            script.async = true;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error("Failed to load Leaflet script"));
            document.head.appendChild(script);
        });
    }

    async renderMap(): Promise<void> {
        if (!this._container) return;

        try {
            await this.loadLeafletResources();

            // @ts-ignore
            const L = window.L;
            if (!L) throw new Error("Leaflet L object not found");

            if (!this._map) {
                // Wait for container to have dimensions
                if (this._container.clientWidth === 0 || this._container.clientHeight === 0) {
                    // Retry shortly if not visible yet (e.g. tab not active)
                    setTimeout(() => this.renderMap(), 500);
                    return;
                }

                this._map = L.map(this._container).setView(this._center, this._zoom);

                this._tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 19,
                    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                }).addTo(this._map);

                // Add a sample marker
                L.marker(this._center).addTo(this._map)
                    .bindPopup(`<b>${this.getTitle()}</b><br>Lat: ${this._center[0]}<br>Lng: ${this._center[1]}`)
                    .openPopup();

                this._mapReady = true;

                // Handle resize
                const resizeObserver = new ResizeObserver(() => {
                    if (this._map && this._mapReady) {
                        this._map.invalidateSize();
                    }
                });
                resizeObserver.observe(this._container);

                // Force size invalidation just in case
                setTimeout(() => this._map.invalidateSize(), 100);

            } else {
                this._map.setView(this._center, this._zoom);
            }

        } catch (err) {
            console.error("[LeafletWidget] Error rendering map:", err);
            this._container.innerHTML = `<div style="padding:10px; color:red">Error rendering map: ${(err as Error).message}</div>`;
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
