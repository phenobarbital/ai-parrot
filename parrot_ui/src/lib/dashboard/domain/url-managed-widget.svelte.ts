import { Widget, type WidgetConfig } from "./widget.svelte.js";
import type { ConfigTab } from "./types.js";

export interface UrlManagedConfig extends WidgetConfig {
    url?: string;
    path?: string;
}

const sanitizeValue = (value?: string | null): string => {
    if (!value || value === "undefined") {
        return "";
    }
    return value;
};

export class UrlManagedWidget extends Widget {
    url = $state<string>("");
    path = $state<string>("");

    constructor(config: UrlManagedConfig) {
        super(config);
        this.url = sanitizeValue(config.url);
        this.path = sanitizeValue(config.path);
    }

    addUrl(url: string): void {
        this.setUrl(url);
    }

    addPath(path: string): void {
        this.setPath(path);
    }

    setUrl(url: string): void {
        this.url = sanitizeValue(url);
    }

    setPath(path: string): void {
        this.path = sanitizeValue(path);
    }

    getUrl(): string {
        return this.url;
    }

    getPath(): string {
        return this.path;
    }

    getResolvedSource(): string {
        return this.url || this.path;
    }

    override getConfigTabs(): ConfigTab[] {
        return [...super.getConfigTabs(), this.createUrlConfigTab()];
    }

    override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);
        if (typeof config.url === "string") {
            this.setUrl(config.url);
        }
        if (typeof config.path === "string") {
            this.setPath(config.path);
        }
    }

    protected createUrlConfigTab(): ConfigTab {
        let urlInput: HTMLInputElement | undefined;
        let pathInput: HTMLInputElement | undefined;

        const createInput = (
            label: string,
            value: string,
            placeholder: string,
        ): { wrapper: HTMLDivElement; input: HTMLInputElement } => {
            const group = document.createElement("div");
            Object.assign(group.style, { marginBottom: "16px" });

            const inputLabel = document.createElement("label");
            inputLabel.textContent = label;
            Object.assign(inputLabel.style, {
                display: "block",
                marginBottom: "6px",
                fontSize: "13px",
                fontWeight: "500",
                color: "var(--text, #333)",
            });

            const input = document.createElement("input");
            input.type = "text";
            input.value = value;
            input.placeholder = placeholder;
            Object.assign(input.style, {
                width: "100%",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border, #ddd)",
                fontSize: "14px",
                boxSizing: "border-box",
            });

            group.append(inputLabel, input);
            return { wrapper: group, input };
        };

        return {
            id: "url",
            label: "URL/Path",
            icon: "🔗",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const urlGroup = createInput(
                    "URL",
                    this.url,
                    "https://example.com",
                );
                urlInput = urlGroup.input;

                const pathGroup = createInput(
                    "Path",
                    this.path,
                    "/path/to/resource",
                );
                pathInput = pathGroup.input;

                container.append(urlGroup.wrapper, pathGroup.wrapper);
            },
            save: () => ({
                url: urlInput?.value ?? this.url,
                path: pathInput?.value ?? this.path,
            }),
        };
    }
}
