import { Widget, type WidgetConfig } from "./widget.svelte.js";
import type { ConfigTab } from "./types.js";

export interface ContentWidgetConfig extends WidgetConfig {
    content?: string;
}

export class ContentWidget extends Widget {
    content = $state<string>("");

    constructor(config: ContentWidgetConfig) {
        super({
            ...config,
            title: config.title || "Content Widget",
            icon: config.icon ?? "📝",
        });
        this.content = config.content ?? "";
    }

    override getConfigTabs(): ConfigTab[] {
        return [...super.getConfigTabs(), this.createContentConfigTab()];
    }

    override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);
        if (typeof config.content === "string") {
            this.content = config.content;
        }
    }

    protected createContentConfigTab(): ConfigTab {
        let textarea: HTMLTextAreaElement | undefined;

        // In a real implementation, we would import a WYSIWYG library here
        // For now, we use a textarea with a note

        return {
            id: "content-settings",
            label: "Content",
            icon: "📝",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const label = document.createElement("label");
                label.textContent = "Content (HTML/Markdown supported)";
                Object.assign(label.style, {
                    display: "block",
                    marginBottom: "8px",
                    fontWeight: "500"
                });

                textarea = document.createElement("textarea");
                textarea.value = this.content;
                textarea.placeholder = "Enter text, HTML, or Markdown...";
                Object.assign(textarea.style, {
                    width: "100%",
                    height: "300px",
                    padding: "10px",
                    border: "1px solid var(--border, #ccc)",
                    borderRadius: "4px",
                    fontFamily: "monospace",
                    resize: "vertical"
                });

                container.append(label, textarea);
            },
            save: () => ({
                content: textarea?.value ?? this.content
            })
        };
    }
}
