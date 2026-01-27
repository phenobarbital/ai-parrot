import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import { el, on } from "./utils.js";
import { mount, unmount } from "svelte";
import DataTable from "$lib/components/agents/DataTable.svelte";
import * as echarts from "echarts";

// Import types from agent (assuming they are available or defining subset)
// We need to use 'any' or define interface here to avoid importing from $lib/types/agent which might be TS-only and not available in this pure JS/TS lib folder without path alias issues?
// relative import is safer if they are in same tree.
// But dashboard lib seems to be standalone. Let's define the interface we need.

export interface AgentMessageData {
    content: string;
    output_mode?: string;
    data?: any;
    code?: string;
    tool_calls?: any[];
}

export interface AgentWidgetOptions extends WidgetOptions {
    message: AgentMessageData;
    onReload?: (widget: AgentWidget) => void;
    onExplain?: (widget: AgentWidget) => void;
}

/**
 * AgentWidget - Polymorphic widget for Agent Responses.
 * Renders Markdown, Charts, Maps, etc. based on message content.
 */
export class AgentWidget extends Widget {
    private message: AgentMessageData;
    private _contentContainer: HTMLElement | undefined;
    private _dataContainer: HTMLElement | undefined;
    private _showingData = false;

    // Child widgets/renderers references
    private _chartInstance: any = null;
    private _resizeObserver: ResizeObserver | null = null;
    private _dataTableInstance: any = null; // Svelte component instance

    constructor(opts: AgentWidgetOptions) {
        super({
            icon: "🤖",
            ...opts,
            title: opts.title || "Agent Response",
            // Add custom toolbar buttons
            toolbar: [
                ...(opts.toolbar || []),
                {
                    id: "reload",
                    title: "Regenerate Response",
                    icon: "↻",
                    onClick: (w) => opts.onReload?.(w as AgentWidget),
                    visible: () => !!opts.onReload
                },
                {
                    id: "explain",
                    title: "Explain this",
                    icon: "❓",
                    onClick: (w) => opts.onExplain?.(w as AgentWidget),
                    visible: () => !!opts.onExplain
                }
            ]
        });

        this.message = opts.message;
        this.initializeAgentWidget();
    }

    private initializeAgentWidget(): void {
        this._contentContainer = el("div", { class: "agent-widget-content" });
        Object.assign(this._contentContainer.style, {
            width: "100%",
            height: "100%",
            overflow: "auto",
            display: "flex",
            flexDirection: "column",
            position: "relative"
        });

        this._dataContainer = el("div", { class: "agent-widget-data" });
        Object.assign(this._dataContainer.style, {
            width: "100%",
            height: "100%",
            overflow: "auto",
            display: "none",
            padding: "1rem",
            background: "var(--base-100, #fff)",
            position: "absolute",
            top: "0",
            left: "0",
            zIndex: "10"
        });

        this.setContent(el("div", { style: "width:100%;height:100%;position:relative;" },
            this._contentContainer,
            this._dataContainer
        ));

        // Footer for "Show Data"
        const footerBtn = el("button", {
            class: "agent-widget-footer-btn",
            style: "width: 100%; padding: 4px; font-size: 0.8rem; background: transparent; border: none; cursor: pointer; opacity: 0.7;"
        }, "Show Data");

        on(footerBtn, "click", () => this.toggleData());

        // Only show footer button if there is data
        if (this.message.data || this.message.content.length > 500) {
            this.footerSection.appendChild(footerBtn);
            this.footerSection.style.display = "block";
            this.footerSection.style.padding = "0";
            this.footerSection.style.borderTop = "1px solid var(--border, #eee)";
        }

        // Use setTimeout to allow render to complete before heavy lifting
        setTimeout(() => this.renderContent(), 0);
    }

    private toggleData(): void {
        this._showingData = !this._showingData;
        if (this._showingData) {
            this._contentContainer!.style.display = "none";
            this._dataContainer!.style.display = "block";
            this.renderDataView();
            (this.footerSection.firstChild as HTMLElement).textContent = "Show Visual";
        } else {
            this._dataContainer!.style.display = "none";
            this._contentContainer!.style.display = "flex";
            (this.footerSection.firstChild as HTMLElement).textContent = "Show Data";
        }
    }

    private renderDataView(): void {
        if (!this._dataContainer) return;
        if (this._dataContainer.innerHTML !== "") {
            // Already rendered, just ensure visibility
            return;
        }

        const dataToShow = this.message.data ?? this.message.tool_calls;

        // 1. If we have array data, render DataTable
        if (Array.isArray(dataToShow) && dataToShow.length > 0) {
            this._dataTableInstance = mount(DataTable, {
                target: this._dataContainer,
                props: {
                    data: dataToShow,
                    title: "Data View"
                }
            });
            return;
        }

        // 2. Fallback: JSON Pre
        const pre = el("pre", {
            style: "font-family: monospace; font-size: 0.8rem; white-space: pre-wrap; word-break: break-all; color: var(--db-text, #fff); background: var(--db-surface-2, #333); padding: 1rem; border-radius: 4px;"
        });

        const content = dataToShow ?? this.message.content;
        pre.textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);

        this._dataContainer.appendChild(pre);
    }

    protected override onDestroy(): void {
        if (this._dataTableInstance) {
            unmount(this._dataTableInstance);
            this._dataTableInstance = null;
        }
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this._chartInstance) {
            this._chartInstance.dispose();
            this._chartInstance = null;
        }
    }

    private async renderContent(): Promise<void> {
        if (!this._contentContainer) return;

        const { content, output_mode, data } = this.message;

        // 1. ECharts
        if (output_mode === "echarts" || (data && (data.series || data.xAxis))) {
            return this.renderECharts(data || JSON.parse(content));
        }

        // 2. HTML / IFrame
        if (output_mode === "html" || content.trim().startsWith("<!DOCTYPE html") || content.trim().startsWith("<html")) {
            return this.renderHTML(content);
        }

        // 3. Vega
        if (output_mode === "vega" || (data && (data.$schema && data.$schema.includes("vega")))) {
            // For now fall back to json, but ideally impl Vega
            // return this.renderVega(data);
        }

        // 4. Image
        if (output_mode === "image" || (typeof content === 'string' && (content.startsWith("data:image") || content.match(/^https?:\/\/.*(png|jpg|jpeg|gif)$/i)))) {
            return this.renderImage(content);
        }

        // 5. Default: Markdown
        return this.renderMarkdown(content);
    }

    private async renderECharts(option: any): Promise<void> {
        if (!this._contentContainer) return;

        const chartDiv = el("div", { style: "width: 100%; height: 100%; min-height: 300px;" });
        this._contentContainer.appendChild(chartDiv);

        try {
            // Lazy load ECharts from CDN (same as EChartsWidget)
            // @ts-ignore
            if (!(window as any).echarts) {
                // @ts-ignore
                await import("https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js");
            }

            // @ts-ignore
            const echarts = (window as any).echarts;
            this._chartInstance = echarts.init(chartDiv);

            console.log('[AgentWidget] ECharts Option:', option);
            this._chartInstance.setOption(option);

            this._resizeObserver = new ResizeObserver(() => {
                this._chartInstance?.resize();
            });
            this._resizeObserver.observe(chartDiv);

        } catch (err: any) {
            console.error('[AgentWidget] ECharts Error:', err);
            chartDiv.innerHTML = `<div style="padding:10px; color:red; overflow:auto; height:100%">
                <p><strong>Error loading chart:</strong> ${err.message}</p>
                <pre style="font-size:0.7em">${err.stack}</pre>
                <p>Check console for options.</p>
            </div>`;
        }
    }

    private renderHTML(html: string): void {
        if (!this._contentContainer) return;
        // Check if it's a full page or just a snippet
        if (html.includes("<html") || html.includes("<!DOCTYPE")) {
            // Use iframe for full isolation
            const iframe = el("iframe", {
                style: "width: 100%; height: 100%; border: none; background: white;",
                sandbox: "allow-scripts allow-popups allow-forms allow-same-origin" // Relaxed sandbox for interactivity
            });
            this._contentContainer.appendChild(iframe);
            // Write content
            setTimeout(() => {
                const doc = iframe.contentDocument;
                if (doc) {
                    doc.open();
                    doc.write(html);
                    doc.close();
                }
            }, 50);
        } else {
            // Snippet - unsafe innerHTML? 
            // Better to use iframe always for agents to prevent style leaks
            const iframe = el("iframe", {
                style: "width: 100%; height: 100%; border: none; background: transparent;"
            });
            this._contentContainer.appendChild(iframe);
            setTimeout(() => {
                const doc = iframe.contentDocument;
                if (doc) {
                    doc.open();
                    // Inject basic styles for snippet
                    doc.write(`
                        <style>body { font-family: system-ui, sans-serif; margin: 0; padding: 1rem; color: #333; }</style>
                        ${html}
                    `);
                    doc.close();
                }
            }, 50);
        }
    }

    private renderImage(src: string): void {
        if (!this._contentContainer) return;
        const img = el("img", {
            src,
            style: "max-width: 100%; max-height: 100%; object-fit: contain; margin: auto;"
        });
        this._contentContainer.appendChild(img);
    }

    private async renderMarkdown(markdown: string): Promise<void> {
        if (!this._contentContainer) return;
        const container = el("div", {
            style: "width: 100%; padding: 16px; box-sizing: border-box; font-family: system-ui, sans-serif; line-height: 1.5;"
        });
        this._contentContainer.appendChild(container);

        try {
            // Lazy load marked
            // @ts-ignore
            if (!window.marked) {
                // @ts-ignore
                await import("https://cdn.jsdelivr.net/npm/marked/marked.min.js");
            }
            // @ts-ignore
            container.innerHTML = window.marked.parse(markdown);
        } catch (err) {
            container.textContent = markdown;
        }
    }
}
