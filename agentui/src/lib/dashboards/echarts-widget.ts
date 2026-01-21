// echarts-widget.ts - Widget for rendering Apache ECharts
import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";

// Default ECharts spec (simple bar chart)
const DEFAULT_SPEC = {
    title: {
        text: 'ECharts Getting Started Example'
    },
    tooltip: {},
    legend: {
        data: ['sales']
    },
    xAxis: {
        data: ['Shirts', 'Cardigans', 'Chiffons', 'Pants', 'Heels', 'Socks']
    },
    yAxis: {},
    series: [
        {
            name: 'sales',
            type: 'bar',
            data: [5, 20, 36, 10, 10, 20]
        }
    ]
};

export interface EchartsWidgetOptions extends WidgetOptions {
    option?: Record<string, unknown>;
}

/**
 * Widget that renders Apache ECharts.
 */
export class EChartsWidget extends Widget {
    private _container: HTMLElement | undefined;
    private _option: Record<string, unknown>;
    private _chart: any = null; // ECharts instance
    private _resizeObserver: ResizeObserver | null = null;

    constructor(opts: EchartsWidgetOptions) {
        super({
            icon: "📈",
            ...opts,
            title: opts.title || "ECharts",
            onRefresh: async () => this.renderChart(),
        });
        this._option = opts.option ?? DEFAULT_SPEC;

        // Initial setup
        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            overflow: "hidden",
        });

        this.setContent(this._container);

        // Setup resize observer
        this._resizeObserver = new ResizeObserver(() => {
            if (this._chart) {
                this._chart.resize();
            }
        });
        this._resizeObserver.observe(this._container);

        // Render initial chart
        setTimeout(() => this.renderChart(), 0);
    }

    protected override onInit(): void {
        // Element created in constructor
    }

    protected override onDestroy(): void {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this._chart) {
            this._chart.dispose();
            this._chart = null;
        }
    }

    async renderChart(): Promise<void> {
        if (!this._container) return;

        try {
            // Lazy load ECharts from CDN
            if (!(window as any).echarts) {
                this._container.innerHTML = "Loading ECharts...";
                // @ts-ignore
                await import("https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js");
            }

            // Clear loading message if present
            if (this._container.innerHTML.startsWith("Loading")) {
                this._container.innerHTML = "";
            }

            // Initialize chart if needed
            if (!this._chart) {
                // @ts-ignore
                this._chart = (window as any).echarts.init(this._container);
            }

            // Set options
            this._chart.setOption(this._option);

        } catch (err) {
            console.error("[EChartsWidget] Error rendering chart:", err);
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
            this.createAdvancedTab()
        ];
    }

    protected override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);

        if (typeof config.option === "string") {
            try {
                this._option = JSON.parse(config.option);
                this.renderChart();
            } catch (e) {
                console.error("[EChartsWidget] Invalid JSON option in config");
            }
        }
    }

    private createAdvancedTab(): ConfigTab {
        let optionInput: HTMLTextAreaElement;

        return {
            id: "advanced",
            label: "Advanced",
            icon: "⚙️",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const group = document.createElement("div");
                Object.assign(group.style, {
                    display: "flex",
                    flexDirection: "column",
                    height: "100%"
                });

                const label = document.createElement("label");
                label.textContent = "ECharts JSON Configuration";
                Object.assign(label.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });

                optionInput = document.createElement("textarea");
                optionInput.value = JSON.stringify(this._option, null, 2);
                Object.assign(optionInput.style, {
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

                group.append(label, optionInput);
                container.appendChild(group);
            },
            save: () => ({
                option: optionInput?.value ?? JSON.stringify(this._option),
            }),
        };
    }
}
