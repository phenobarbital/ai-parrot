import type { WidgetConfig } from "./widget.svelte.js";
import { UrlManagedWidget, type UrlManagedConfig } from "./url-managed-widget.svelte.js";

export interface ImageWidgetConfig extends UrlManagedConfig {
    alt?: string;
    objectFit?: "contain" | "cover" | "fill" | "none" | "scale-down";
}

export class ImageWidget extends UrlManagedWidget {
    altText = $state<string>("");
    objectFit = $state<"contain" | "cover" | "fill" | "none" | "scale-down">(
        "contain",
    );
    refreshToken = $state<number>(0);

    constructor(config: ImageWidgetConfig) {
        const refreshHandler: WidgetConfig["onRefresh"] = async (widget) => {
            if (widget instanceof ImageWidget) {
                widget.refreshImage();
            }
        };

        const { alt, objectFit, ...baseConfig } = config;
        super({
            ...baseConfig,
            title: config.title || "Image",
            icon: config.icon ?? "🖼️",
            onRefresh: refreshHandler,
        });

        this.altText = alt ?? config.title ?? "Image";
        this.objectFit = objectFit ?? "contain";
    }

    refreshImage(): void {
        this.refreshToken = Date.now();
    }

    getImageSource(): string {
        const source = this.getResolvedSource();
        if (!source) {
            return "";
        }
        if (!this.refreshToken) {
            return source;
        }
        const separator = source.includes("?") ? "&" : "?";
        return `${source}${separator}_t=${this.refreshToken}`;
    }

    setAlt(text: string): void {
        this.altText = text;
    }

    setObjectFit(
        fit: "contain" | "cover" | "fill" | "none" | "scale-down",
    ): void {
        this.objectFit = fit;
    }
}
