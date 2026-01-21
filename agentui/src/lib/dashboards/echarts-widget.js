// echarts-widget.ts - Widget for rendering Apache ECharts
import { Widget } from "./widget.js";
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
/**
 * Widget that renders Apache ECharts.
 */
export class EChartsWidget extends Widget {
    _container;
    _option;
    _chart = null; // ECharts instance
    _resizeObserver = null;
    constructor(opts) {
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
    initializeElement() {
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
    onInit() {
        // Element created in constructor
    }
    onDestroy() {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this._chart) {
            this._chart.dispose();
            this._chart = null;
        }
    }
    async renderChart() {
        if (!this._container)
            return;
        try {
            // Lazy load ECharts from CDN
            if (!window.echarts) {
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
                this._chart = window.echarts.init(this._container);
            }
            // Set options
            this._chart.setOption(this._option);
        }
        catch (err) {
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
    getConfigTabs() {
        return [
            ...super.getConfigTabs(),
            this.createAdvancedTab()
        ];
    }
    onConfigSave(config) {
        super.onConfigSave(config);
        if (typeof config.option === "string") {
            try {
                this._option = JSON.parse(config.option);
                this.renderChart();
            }
            catch (e) {
                console.error("[EChartsWidget] Invalid JSON option in config");
            }
        }
    }
    createAdvancedTab() {
        let optionInput;
        return {
            id: "advanced",
            label: "Advanced",
            icon: "⚙️",
            render: (container) => {
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
//# sourceMappingURL=echarts-widget.js.map