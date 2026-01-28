// html-widget.ts - Widget for rendering HTML content with WYSIWYG editor
import { Widget } from "./widget.js";
import type { WidgetOptions } from "./types.js";
import type { ConfigTab } from "./widget-config-modal.js";
import { el } from "./utils.js";

interface HTMLWidgetOptions extends WidgetOptions {
    content?: string;
}

/**
 * Widget that renders HTML content.
 */
export class HTMLWidget extends Widget {
    private _container: HTMLElement | undefined;
    private _content: string = "<h1>Hello HTML</h1><p>Edit this content in settings.</p>";

    constructor(opts: HTMLWidgetOptions) {
        super({
            icon: "📰",
            ...opts,
            title: opts.title || "HTML Content",
            onRefresh: async () => this.renderHTML(),
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

        setTimeout(() => this.renderHTML(), 0);
    }

    protected override onInit(): void { }

    async renderHTML(): Promise<void> {
        if (!this._container) return;
        this._container.innerHTML = this._content;
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
            this.renderHTML();
        }
    }

    private createContentTab(): ConfigTab {
        let editorContainer: HTMLElement;
        let quillInstance: any;

        return {
            id: "content",
            label: "Content",
            icon: "📝",
            render: async (container: HTMLElement) => {
                container.innerHTML = "";

                const group = el("div");
                Object.assign(group.style, { display: "flex", flexDirection: "column", height: "100%", minHeight: "400px" });

                const label = el("label");
                label.textContent = "HTML Content";
                Object.assign(label.style, { marginBottom: "6px", fontSize: "12px", fontWeight: "bold" });

                editorContainer = el("div");
                Object.assign(editorContainer.style, {
                    flex: "1",
                    background: "#fff",
                    color: "#000",
                });

                group.appendChild(label);
                group.appendChild(editorContainer);
                container.appendChild(group);

                // Load Quill if needed
                // @ts-ignore
                if (!window.Quill) {
                    const link = document.createElement("link");
                    link.rel = "stylesheet";
                    link.href = "https://cdn.quilljs.com/1.3.6/quill.snow.css";
                    document.head.appendChild(link);

                    // @ts-ignore
                    await import("https://cdn.quilljs.com/1.3.6/quill.min.js");
                }

                // Initialize Quill
                // @ts-ignore
                quillInstance = new window.Quill(editorContainer, {
                    theme: 'snow',
                    modules: {
                        toolbar: [
                            [{ 'header': [1, 2, 3, false] }],
                            ['bold', 'italic', 'underline', 'strike'],
                            ['blockquote', 'code-block'],
                            [{ 'list': 'ordered' }, { 'list': 'bullet' }],
                            [{ 'color': [] }, { 'background': [] }],
                            ['link', 'image', 'video'],
                            ['clean']
                        ]
                    }
                });

                // Set initial content
                // Use a slight delay to ensure editor is ready
                setTimeout(() => {
                    if (quillInstance) {
                        // Manually paste HTML into the editor
                        const delta = quillInstance.clipboard.convert(this._content);
                        quillInstance.setContents(delta, 'silent');
                    }
                }, 50);

            },
            save: () => {
                // Get HTML content
                return {
                    content: quillInstance ? quillInstance.root.innerHTML : this._content
                };
            }
        };
    }
}
