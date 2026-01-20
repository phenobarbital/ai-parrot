// markdown-widget.ts - Widget for rendering Markdown as HTML
import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";

interface MarkdownWidgetOptions extends WidgetOptions {
    content?: string;
}

/**
 * Widget that renders Markdown content.
 */
export class MarkdownWidget extends Widget {
    private _container: HTMLElement | undefined;
    private _content: string = "# Hello Markdown\n\nEdit this content in settings.";

    constructor(opts: MarkdownWidgetOptions) {
        super({
            icon: "📝",
            ...opts,
            title: opts.title || "Markdown",
            onRefresh: async () => this.renderMarkdown(),
        });

        if (opts.content) this._content = opts.content;

        this.initializeElement();
    }

    private initializeElement(): void {
        this._container = document.createElement("div");
        Object.assign(this._container.style, {
            width: "100%",
            height: "100%",
            overflow: "auto",
            padding: "16px",
            boxSizing: "border-box",
            fontFamily: "system-ui, -apple-system, sans-serif",
            lineHeight: "1.5",
        });
        this.setContent(this._container);

        setTimeout(() => this.renderMarkdown(), 0);
    }

    protected override onInit(): void { }

    async renderMarkdown(): Promise<void> {
        if (!this._container) return;

        try {
            // Lazy load marked
            // @ts-ignore
            if (!window.marked) {
                // @ts-ignore
                await import("https://cdn.jsdelivr.net/npm/marked/marked.min.js");
            }

            // @ts-ignore
            const html = window.marked.parse(this._content);
            this._container.innerHTML = html;

        } catch (err) {
            console.error("[MarkdownWidget] Error rendering markdown:", err);
            if (this._container) this._container.textContent = "Error loading markdown renderer.";
        }
    }

    // === Config ===

    override getConfigTabs(): ConfigTab[] {
        return [
            ...super.getConfigTabs(),
            this.createContentTab()
        ];
    }

    protected override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);

        if (typeof config.content === "string") {
            this._content = config.content;
            this.renderMarkdown();
        }
    }

    private createContentTab(): ConfigTab {
        let contentInput: HTMLTextAreaElement;

        return {
            id: "content",
            label: "Content",
            icon: "📃",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const group = document.createElement("div");
                Object.assign(group.style, { display: "flex", flexDirection: "column", height: "100%" });

                const label = document.createElement("label");
                label.textContent = "Markdown Content";
                Object.assign(label.style, { marginBottom: "6px", fontSize: "12px", fontWeight: "bold" });

                contentInput = document.createElement("textarea");
                contentInput.value = this._content;
                Object.assign(contentInput.style, {
                    flex: "1",
                    width: "100%",
                    padding: "8px",
                    borderRadius: "4px",
                    border: "1px solid #ddd",
                    resize: "none",
                    fontFamily: "monospace",
                    fontSize: "13px",
                    boxSizing: "border-box",
                });

                group.appendChild(label);
                group.appendChild(contentInput);
                container.appendChild(group);
            },
            save: () => ({
                content: contentInput.value
            })
        };
    }
}
