// markdown-widget.ts - Widget for rendering Markdown as HTML
import { Widget } from "./widget.js";
/**
 * Widget that renders Markdown content.
 */
export class MarkdownWidget extends Widget {
    _container;
    _content = "# Hello Markdown\n\nEdit this content in settings.";
    constructor(opts) {
        super({
            icon: "📝",
            ...opts,
            title: opts.title || "Markdown",
            onRefresh: async () => this.renderMarkdown(),
        });
        if (opts.content)
            this._content = opts.content;
        this.initializeElement();
    }
    initializeElement() {
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
    onInit() { }
    async renderMarkdown() {
        if (!this._container)
            return;
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
        }
        catch (err) {
            console.error("[MarkdownWidget] Error rendering markdown:", err);
            if (this._container)
                this._container.textContent = "Error loading markdown renderer.";
        }
    }
    // === Config ===
    getConfigTabs() {
        return [
            ...super.getConfigTabs(),
            this.createContentTab()
        ];
    }
    onConfigSave(config) {
        super.onConfigSave(config);
        if (typeof config.content === "string") {
            this._content = config.content;
            this.renderMarkdown();
        }
    }
    createContentTab() {
        let contentInput;
        return {
            id: "content",
            label: "Content",
            icon: "📃",
            render: (container) => {
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
//# sourceMappingURL=markdown-widget.js.map