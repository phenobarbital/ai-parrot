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
        let editor; // EasyMDE instance
        let textarea;
        return {
            id: "content",
            label: "Content",
            icon: "📃",
            render: async (container) => {
                container.innerHTML = "";
                Object.assign(container.style, {
                    display: "flex",
                    flexDirection: "column",
                    height: "100%",
                    overflow: "hidden" // Let editor handle scroll
                });
                // Load EasyMDE CSS if not loaded
                if (!document.getElementById("easymde-css")) {
                    const link = document.createElement("link");
                    link.id = "easymde-css";
                    link.rel = "stylesheet";
                    link.href = "https://cdn.jsdelivr.net/npm/easymde/dist/easymde.min.css";
                    document.head.appendChild(link);
                }
                const wrapper = document.createElement("div");
                Object.assign(wrapper.style, {
                    flex: "1",
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                    position: "relative"
                });
                const loader = document.createElement("div");
                loader.textContent = "Loading editor...";
                Object.assign(loader.style, { padding: "20px", color: "#666", textAlign: "center" });
                wrapper.appendChild(loader);
                textarea = document.createElement("textarea");
                textarea.value = this._content;
                textarea.style.display = "none";
                wrapper.appendChild(textarea);
                container.appendChild(wrapper);
                const loadScript = () => {
                    return new Promise((resolve, reject) => {
                        // @ts-ignore
                        if (window.EasyMDE)
                            return resolve();
                        const s = document.createElement("script");
                        s.src = "https://cdn.jsdelivr.net/npm/easymde/dist/easymde.min.js";
                        s.onload = () => resolve();
                        s.onerror = () => reject(new Error("Failed to load EasyMDE script"));
                        document.head.appendChild(s);
                    });
                };
                try {
                    await loadScript();
                    loader.remove();
                    textarea.style.display = "block";
                    // @ts-ignore
                    if (window.EasyMDE) {
                        // @ts-ignore
                        editor = new window.EasyMDE({
                            element: textarea,
                            initialValue: this._content,
                            spellChecker: false,
                            status: false,
                            placeholder: "Type your markdown here...",
                            forceSync: true, // Sync to textarea on change
                            minHeight: "300px",
                            maxHeight: "500px",
                            toolbar: [
                                "bold", "italic", "heading", "|",
                                "quote", "unordered-list", "ordered-list", "|",
                                "link", "image", "|",
                                "preview", "side-by-side", "fullscreen", "|"
                            ]
                        });
                        // Fix for EasyMDE in modals: sometimes needs a refresh
                        setTimeout(() => {
                            if (editor)
                                editor.codemirror.refresh();
                        }, 100);
                    }
                    else {
                        console.error("EasyMDE loaded but window.EasyMDE is missing");
                        textarea.style.display = "block";
                    }
                }
                catch (e) {
                    console.error("Failed to load EasyMDE", e);
                    loader.textContent = "Error loading editor.";
                    loader.style.color = "red";
                    textarea.style.display = "block";
                }
            },
            onShow: () => {
                if (editor) {
                    console.log("[MarkdownWidget] onShow: refreshing editor");
                    editor.codemirror.refresh();
                }
            },
            save: () => {
                let val = "";
                if (editor) {
                    val = editor.value();
                    // Cleanup editor to avoid memory leaks if we were to re-open
                    editor.toTextArea();
                    editor = null;
                }
                else if (textarea) {
                    val = textarea.value;
                }
                return { content: val };
            }
        };
    }
}
//# sourceMappingURL=markdown-widget.js.map