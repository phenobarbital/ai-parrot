// echarts-widget.ts - Widget for rendering Apache ECharts
import { BaseChartWidget, type BaseChartWidgetOptions } from "./base-chart-widget.js";
import type { ConfigTab } from "./widget-config-modal.js";

// Default ECharts spec (simple bar chart)
const DEFAULT_OPTION = {
    title: { text: "ECharts Example" },
    tooltip: {},
    legend: { data: ["sales"] },
    xAxis: { data: ["A", "B", "C"] },
    yAxis: {},
    series: [{ name: "sales", type: "bar", data: [5, 20, 36] }]
};

export interface EchartsWidgetOptions extends BaseChartWidgetOptions {
    option?: Record<string, unknown>; // Advanced URL/JSON override
}

export class EChartsWidget extends BaseChartWidget {
    private _container: HTMLElement | undefined;
    private _advancedOption: Record<string, unknown> | null = null;
    private _chart: any = null; // ECharts instance
    private _resizeObserver: ResizeObserver | null = null;

    constructor(opts: EchartsWidgetOptions) {
        super({
            ...opts,
            icon: "📈",
            title: opts.title || "ECharts",
        });

        if (opts.option) {
            this._advancedOption = opts.option;
        }

        // BaseChartWidget calls renderData(), which calls renderChartData()
        // We need to initialize the container first
        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            overflow: "hidden",
            flex: "1" // allow it to grow if flex container
        });

        // Set content from BaseChartWidget (ApiWidget)
        this.setContent(this._container);

        // Setup resize observer
        this._resizeObserver = new ResizeObserver(() => {
            if (this._chart) {
                this._chart.resize();
            }
        });
        this._resizeObserver.observe(this._container);
    }

    protected override onDestroy(): void {
        super.onDestroy(); // Call base destroy
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this._chart) {
            this._chart.dispose();
            this._chart = null;
        }
    }

    // Called by BaseChartWidget when data is ready (or updated)
    protected async renderChartData(data: unknown): Promise<void> {
        if (!this._container) return;

        try {
            // Lazy load ECharts
            // @ts-ignore
            if (!(window as any).echarts) {
                this._container.innerHTML = "<div style='display:flex;justify-content:center;align-items:center;height:100%'>Loading ECharts...</div>";
                // @ts-ignore
                await import("https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js");
            }

            // Initialize chart if needed
            if (!this._chart) {
                this._container.innerHTML = ""; // Clear loading
                // @ts-ignore
                this._chart = (window as any).echarts.init(this._container);
            }

            // Determine Option
            let option = this._advancedOption;

            // If no advanced option, build from config + data
            if (!option) {
                option = this.buildOptionFromConfig(data);
            }

            this._chart.setOption(option);
        } catch (err) {
            console.error("[EChartsWidget] Error rendering chart:", err);
            this._container.innerHTML = "Error rendering chart";
        }
    }

    private buildOptionFromConfig(data: unknown): any {
        if (!Array.isArray(data) || data.length === 0) return DEFAULT_OPTION;

        const { type, xField, yField, labelField, dataField } = this.chartConfig;

        // Common defaults
        const base = {
            tooltip: { trigger: 'item' },
            legend: { top: '5%' },
            grid: { top: '15%', left: '3%', right: '4%', bottom: '3%', containLabel: true }
        };

        if (["pie", "donut"].includes(type)) {
            const seriesData = data.map(row => ({
                name: labelField ? row[labelField] : "Unknown",
                value: dataField ? Number(row[dataField]) : 0
            }));

            return {
                ...base,
                series: [{
                    type: 'pie',
                    radius: type === 'donut' ? ['40%', '70%'] : '50%',
                    data: seriesData,
                    emphasis: {
                        itemStyle: {
                            shadowBlur: 10,
                            shadowOffsetX: 0,
                            shadowColor: 'rgba(0, 0, 0, 0.5)'
                        }
                    }
                }]
            };
        } else {
            // Cartesian (Line, Bar, Area)
            // Need xField and yField
            const xCategories = xField ? data.map(r => r[xField]) : [];
            const seriesData = yField ? data.map(r => Number(r[yField])) : [];

            // Map simplified type to ECharts type
            let seriesType = 'bar';
            const seriesExtra: any = {};

            if (type === 'line') seriesType = 'line';
            else if (type === 'area') {
                seriesType = 'line';
                seriesExtra.areaStyle = {};
            } else if (type === 'stacked-area') {
                seriesType = 'line';
                seriesExtra.areaStyle = {};
                seriesExtra.stack = 'Total';
            } else if (type === 'scatter') {
                seriesType = 'scatter';
            }

            return {
                ...base,
                tooltip: { trigger: 'axis' },
                xAxis: {
                    type: 'category',
                    data: xCategories,
                    boundaryGap: type === 'bar' // Lines usually stick to edge?
                },
                yAxis: {
                    type: 'value'
                },
                series: [{
                    data: seriesData,
                    type: seriesType,
                    ...seriesExtra
                }]
            };
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

        if (typeof config.option === "string" && config.option.trim() !== "") {
            try {
                this._advancedOption = JSON.parse(config.option);
            } catch (e) {
                console.error("[EChartsWidget] Invalid JSON option in config");
            }
        } else {
            this._advancedOption = null; // Clear advanced override to use simple config
        }

        // BaseChartWidget.onConfigSave calls renderData()
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
                Object.assign(group.style, { display: "flex", flexDirection: "column", height: "100%" });

                const label = document.createElement("label");
                label.textContent = "ECharts JSON Configuration (Overrides Basic Config)";
                Object.assign(label.style, { display: "block", marginBottom: "6px", fontWeight: "bold" });

                optionInput = document.createElement("textarea");
                optionInput.value = this._advancedOption ? JSON.stringify(this._advancedOption, null, 2) : "";
                optionInput.placeholder = "Paste full ECharts option JSON here...";
                Object.assign(optionInput.style, {
                    flex: "1",
                    fontFamily: "monospace",
                    padding: "8px",
                    border: "1px solid #ccc",
                    borderRadius: "4px"
                });

                group.append(label, optionInput);
                container.appendChild(group);
            },
            save: () => ({
                option: optionInput?.value
            }),
        };
    }
}
