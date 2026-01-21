// vega-widget.ts - Widget for rendering Vega and Vega-Lite charts
import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";

// Default Vega-Lite bar chart spec
const DEFAULT_SPEC = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    description: "A simple bar chart with embedded data.",
    data: {
        values: [
            { "a": "A", "b": 28 },
            { "a": "B", "b": 55 },
            { "a": "C", "b": 43 },
            { "a": "D", "b": 91 },
            { "a": "E", "b": 81 },
            { "a": "F", "b": 53 },
            { "a": "G", "b": 19 },
            { "a": "H", "b": 87 },
            { "a": "I", "b": 52 }
        ]
    },
    mark: "bar",
    encoding: {
        x: { "field": "a", "type": "nominal", "axis": { "labelAngle": 0 } },
        y: { "field": "b", "type": "quantitative" }
    }
};

export interface VegaWidgetOptions extends WidgetOptions {
    spec?: Record<string, unknown>;
}

/**
 * Widget that renders Vega/Vega-Lite charts using vega-embed.
 */
export class VegaWidget extends Widget {
    private _container: HTMLElement | undefined;
    private _spec: Record<string, unknown>;
    private _view: any = null; // Vega view instance

    constructor(opts: VegaWidgetOptions) {
        super({
            icon: "📊",
            ...opts,
            title: opts.title || "Vega Chart",
            onRefresh: async () => this.renderChart(),
        });
        this._spec = opts.spec ?? DEFAULT_SPEC;

        // Initial setup
        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            overflow: "hidden",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
        });

        this.setContent(this._container);

        // Render initial chart
        setTimeout(() => this.renderChart(), 0);
    }

    protected override onInit(): void {
        // Element created in constructor
    }

    protected override onDestroy(): void {
        if (this._view) {
            this._view.finalize();
            this._view = null;
        }
    }

    async renderChart(): Promise<void> {
        if (!this._container) return;

        try {
            this._container.innerHTML = "Loading chart...";

            // Dynamic import of dependencies to ensure version compatibility
            // @ts-ignore
            if (!window.vega) await import("https://cdn.jsdelivr.net/npm/vega@5.30.0/+esm");
            // @ts-ignore
            if (!window.vegaLite) await import("https://cdn.jsdelivr.net/npm/vega-lite@5.19.0/+esm");

            // @ts-ignore
            const { default: vegaEmbed } = await import("https://cdn.jsdelivr.net/npm/vega-embed@6.24.0/+esm");

            // Clear loading message
            this._container.innerHTML = "";

            const result = await vegaEmbed(this._container, this._spec, {
                actions: false,
                renderer: "svg", // Use SVG for better scaling
                tooltip: true,
            });

            this._view = result.view;

            // Fix resizing
            this._view.resize().run();

        } catch (err) {
            console.error("[VegaWidget] Error rendering chart:", err);
            if (this._container) {
                this._container.innerHTML = `
                    <div style="color: red; padding: 10px; text-align: center;">
                        <div style="font-weight: bold; margin-bottom: 5px;">Error rendering chart</div>
                        <div style="font-size: 12px;">${err instanceof Error ? err.message : String(err)}</div>
                    </div>
                `;
            }
        }
    }

    // === Config ===

    override getConfigTabs(): ConfigTab[] {
        return [
            ...super.getConfigTabs(),
            this.createSpecConfigTab()
        ];
    }

    protected override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);

        if (typeof config.spec === "string") {
            try {
                this._spec = JSON.parse(config.spec);
                this.renderChart();
            } catch (e) {
                console.error("[VegaWidget] Invalid JSON spec in config");
            }
        }
    }

    private createSpecConfigTab(): ConfigTab {
        let specInput: HTMLTextAreaElement;

        return {
            id: "vega-spec",
            label: "Spec",
            icon: "📝",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const group = document.createElement("div");
                Object.assign(group.style, {
                    display: "flex",
                    flexDirection: "column",
                    height: "100%"
                });

                const label = document.createElement("label");
                label.textContent = "Vega-Lite JSON Specification";
                Object.assign(label.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });

                specInput = document.createElement("textarea");
                specInput.value = JSON.stringify(this._spec, null, 2);
                Object.assign(specInput.style, {
                    flex: "1",
                    width: "100%",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "12px",
                    fontFamily: "monospace",
                    resize: "none",
                    boxSizing: "border-box",
                });

                group.append(label, specInput);
                container.appendChild(group);
            },
            save: () => ({
                spec: specInput?.value ?? JSON.stringify(this._spec),
            }),
        };
    }
}
