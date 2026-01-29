import { ApiWidget, type ApiWidgetOptions } from "./api-widget.js";
import type { ConfigTab } from "./widget-config-modal.js";
import { Grid } from "gridjs";

export type ChartType = "line" | "bar" | "area" | "stacked-area" | "pie" | "donut" | "scatter";

export interface ChartConfig {
    type: ChartType;
    xField?: string; // For line, bar, area, scatter
    yField?: string; // For line, bar, area, scatter
    labelField?: string; // For pie, donut
    dataField?: string; // For pie, donut
    colorField?: string; // Optional grouping/color
}

export interface BaseChartWidgetOptions extends ApiWidgetOptions {
    /** JavaScript code for data transformation: (data) => transformedData */
    transformCode?: string;
    /** Simplified chart configuration */
    chartConfig?: ChartConfig;
}

export abstract class BaseChartWidget extends ApiWidget {
    protected transformCode: string;
    protected chartConfig: ChartConfig;
    private _transformedData: unknown = null;
    private _footerGrid: Grid | null = null;
    private _footerContainer: HTMLElement | null = null;
    private _isFooterOpen: boolean = false;

    constructor(options: BaseChartWidgetOptions) {
        super(options);
        this.transformCode = options.transformCode ?? "";
        this.chartConfig = options.chartConfig ?? { type: "bar" };

        this.initializeFooter();
    }

    private initializeFooter(): void {
        // Toggle button in footer
        this.updateFooterToggle();

        // Container for the data table (hidden by default)
        this._footerContainer = document.createElement("div");
        Object.assign(this._footerContainer.style, {
            display: "none",
            width: "100%",
            height: "250px", // Fixed height for table view
            borderTop: "1px solid var(--border, #ddd)",
            background: "var(--bg-surface, #fff)",
            overflow: "hidden",
            position: "absolute",
            bottom: "0",
            left: "0",
            zIndex: "10"
        });

        // We append this to the widget element, but we need to manage layout 
        // to not obscure the chart if possible, or overlay it.
        // For now overlay is safer for avoiding layout thrashing.
        this.el.appendChild(this._footerContainer);
    }

    protected updateFooterToggle(): void {
        this.footerSection.innerHTML = "";

        const toggleBtn = document.createElement("button");
        toggleBtn.textContent = this._isFooterOpen ? "Hide Data Table" : `Show Data (${this.getDataCount()} rows)`;
        toggleBtn.className = "widget-footer-btn";
        Object.assign(toggleBtn.style, {
            background: "none",
            border: "none",
            color: "var(--primary, #007bff)",
            cursor: "pointer",
            fontSize: "12px",
            padding: "4px 8px",
            width: "100%",
            textAlign: "left"
        });

        toggleBtn.onclick = () => this.toggleFooter();
        this.footerSection.appendChild(toggleBtn);
        this.footerSection.style.display = ""; // Ensure footer is visible
    }

    private toggleFooter(): void {
        this._isFooterOpen = !this._isFooterOpen;
        if (this._footerContainer) {
            this._footerContainer.style.display = this._isFooterOpen ? "block" : "none";
        }

        if (this._isFooterOpen) {
            this.renderFooterGrid();
        }

        this.updateFooterToggle();
    }

    private getDataCount(): number {
        const data = this.getTransformedData();
        if (Array.isArray(data)) return data.length;
        if (Array.isArray(this.getData())) return (this.getData() as any[]).length;
        return 0;
    }

    protected getTransformedData(): unknown {
        return this._transformedData || this.getData();
    }

    // Override renderData from ApiWidget
    protected override renderData(): void {
        const rawData = this.getData();
        this._transformedData = this.applyTransformation(rawData);

        // Render the actual chart (abstract method or override in subclass)
        this.renderChartData(this._transformedData);

        // Update footer count
        this.updateFooterToggle();

        // Refresh grid if open
        if (this._isFooterOpen) {
            this.renderFooterGrid();
        }
    }

    // Subclasses must implement this to render the chart
    protected abstract renderChartData(data: unknown): void;

    private applyTransformation(data: unknown): unknown {
        if (!this.transformCode || !this.transformCode.trim()) return data;

        try {
            // Simple safety check - obviously not secure against malicious user, but intended for dashboard creators
            // We pass 'data' and 'lodash' (if available globally) to the function
            const func = new Function("data", "_", `
                try {
                    ${this.transformCode.includes("return") ? "" : "return ("}
                    ${this.transformCode}
                    ${this.transformCode.includes("return") ? "" : ");"}
                } catch(e) {
                    console.error("Transformation error", e);
                    return data;
                }
            `);

            // @ts-ignore
            return func(data, (window as any)._);
        } catch (e) {
            console.error("[BaseChartWidget] Error creating transformation function:", e);
            return data;
        }
    }

    private async renderFooterGrid(): Promise<void> {
        if (!this._footerContainer) return;

        const data = this.getTransformedData();
        if (!Array.isArray(data) || data.length === 0) {
            this._footerContainer.innerHTML = "<div style='padding:10px; color:#888;'>No tabular data available</div>";
            return;
        }

        // Setup GridJS
        this._footerContainer.innerHTML = "";

        // Auto-detect columns
        const keys = Object.keys(data[0]);
        const columns = keys.map(k => ({ id: k, name: k }));

        try {
            // We need to import styles for gridjs if not already
            if (!document.getElementById("gridjs-styles")) {
                const link = document.createElement("link");
                link.id = "gridjs-styles";
                link.rel = "stylesheet";
                link.href = "https://cdn.jsdelivr.net/npm/gridjs/dist/theme/mermaid.min.css";
                document.head.appendChild(link);
            }

            this._footerGrid = new Grid({
                columns: columns,
                data: data,
                pagination: {
                    enabled: true,
                    limit: 5
                },
                search: true,
                sort: true,
                height: "250px",
                fixedHeader: true,
                style: {
                    container: {
                        fontSize: '12px'
                    },
                    table: {
                        'white-space': 'nowrap'
                    }
                }
            });

            this._footerGrid.render(this._footerContainer);
        } catch (e) {
            console.error("[BaseChartWidget] Grid render error:", e);
        }
    }

    // === Configuration ===

    override getConfigTabs(): ConfigTab[] {
        return [
            ...super.getConfigTabs(), // Url, Api options
            this.createChartConfigTab(),
            this.createTransformConfigTab()
        ];
    }

    protected override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);

        if (typeof config.transformCode === "string") {
            this.transformCode = config.transformCode;
        }

        // Chart Config
        if (typeof config.chartType === "string") {
            this.chartConfig = {
                type: config.chartType as ChartType,
                xField: config.chartXField as string,
                yField: config.chartYField as string,
                labelField: config.chartLabelField as string,
                dataField: config.chartDataField as string,
                colorField: config.chartColorField as string,
            };
        }

        // Re-process
        this.renderData();
    }

    private createTransformConfigTab(): ConfigTab {
        let codeInput: HTMLTextAreaElement;

        return {
            id: "transform",
            label: "Transform",
            icon: "⚡",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const group = document.createElement("div");
                Object.assign(group.style, { display: "flex", flexDirection: "column", height: "100%" });

                const label = document.createElement("label");
                label.innerHTML = "Transformation (JS Body)<br><small style='font-weight:normal; color:#666'>Available: <code>data</code>, <code>_</code> (lodash)</small>";
                Object.assign(label.style, { marginBottom: "6px", fontWeight: "bold" });

                codeInput = document.createElement("textarea");
                codeInput.value = this.transformCode;
                codeInput.placeholder = "return data.map(d => ({ ...d, value: d.value * 2 }));";
                Object.assign(codeInput.style, {
                    flex: "1",
                    fontFamily: "monospace",
                    padding: "8px",
                    border: "1px solid #ccc",
                    borderRadius: "4px"
                });

                group.append(label, codeInput);
                container.appendChild(group);
            },
            save: () => ({ transformCode: codeInput.value })
        };
    }

    private createChartConfigTab(): ConfigTab {
        let typeSelect: HTMLSelectElement;
        let xInput: HTMLInputElement;
        let yInput: HTMLInputElement;
        let labelInput: HTMLInputElement;
        let dataInput: HTMLInputElement;

        return {
            id: "chart-settings",
            label: "Chart",
            icon: "📊",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                // Chart Type
                const typeGroup = this.createFormGroup("Chart Type");
                typeSelect = document.createElement("select");
                ["line", "bar", "area", "stacked-area", "pie", "donut", "scatter"].forEach(t => {
                    const opt = document.createElement("option");
                    opt.value = t;
                    opt.textContent = t.charAt(0).toUpperCase() + t.slice(1);
                    if (t === this.chartConfig.type) opt.selected = true;
                    typeSelect.appendChild(opt);
                });
                this.styleInput(typeSelect);
                typeGroup.appendChild(typeSelect);
                container.appendChild(typeGroup);

                // Axis Settings (Line/Bar/Area)
                const axisDiv = document.createElement("div");

                const xGroup = this.createFormGroup("X Axis Field");
                xInput = document.createElement("input");
                xInput.value = this.chartConfig.xField ?? "";
                this.styleInput(xInput);
                xGroup.appendChild(xInput);

                const yGroup = this.createFormGroup("Y Axis Field");
                yInput = document.createElement("input");
                yInput.value = this.chartConfig.yField ?? "";
                this.styleInput(yInput);
                yGroup.appendChild(yInput);

                axisDiv.append(xGroup, yGroup);

                // Pie/Donut Settings
                const pieDiv = document.createElement("div");

                const labelGroup = this.createFormGroup("Label Field");
                labelInput = document.createElement("input");
                labelInput.value = this.chartConfig.labelField ?? "";
                this.styleInput(labelInput);
                labelGroup.appendChild(labelInput);

                const dataGroup = this.createFormGroup("Data Field (Value)");
                dataInput = document.createElement("input");
                dataInput.value = this.chartConfig.dataField ?? "";
                this.styleInput(dataInput);
                dataGroup.appendChild(dataInput);

                pieDiv.append(labelGroup, dataGroup);

                // Toggle visibility based on type
                const updateVisibility = () => {
                    const t = typeSelect.value;
                    if (["pie", "donut"].includes(t)) {
                        axisDiv.style.display = "none";
                        pieDiv.style.display = "block";
                    } else {
                        axisDiv.style.display = "block";
                        pieDiv.style.display = "none";
                    }
                };

                typeSelect.onchange = updateVisibility;
                updateVisibility(); // Init

                container.append(axisDiv, pieDiv);
            },
            save: () => ({
                chartType: typeSelect.value,
                chartXField: xInput.value,
                chartYField: yInput.value,
                chartLabelField: labelInput.value,
                chartDataField: dataInput.value
            })
        };
    }

    private createFormGroup(label: string): HTMLElement {
        const div = document.createElement("div");
        div.style.marginBottom = "10px";
        const l = document.createElement("label");
        l.textContent = label;
        l.style.display = "block";
        l.style.fontWeight = "bold";
        l.style.marginBottom = "5px";
        div.appendChild(l);
        return div;
    }

    private styleInput(el: HTMLElement) {
        Object.assign(el.style, {
            width: "100%",
            padding: "5px",
            boxSizing: "border-box",
            borderRadius: "4px",
            border: "1px solid #ccc"
        });
    }
}
