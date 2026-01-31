import type { WidgetConfig } from "./widget.svelte.js";
import { UrlManagedWidget, type UrlManagedConfig } from "./url-managed-widget.svelte.js";

export interface IFrameWidgetConfig extends UrlManagedConfig {
    sandbox?: string;
    allowFullscreen?: boolean;
}

export class IFrameWidget extends UrlManagedWidget {
    sandboxAttr = $state<string>("allow-scripts allow-same-origin");
    allowFullscreen = $state<boolean>(true);
    refreshToken = $state<number>(0);

    constructor(config: IFrameWidgetConfig) {
        const refreshHandler: WidgetConfig["onRefresh"] = async (widget) => {
            if (widget instanceof IFrameWidget) {
                widget.refreshFrame();
            }
        };

        const { sandbox, allowFullscreen, ...baseConfig } = config;
        super({
            ...baseConfig,
            title: config.title || "Web Content",
            icon: config.icon ?? "🌐",
            onRefresh: refreshHandler,
        });

        this.sandboxAttr = sandbox ?? "allow-scripts allow-same-origin";
        this.allowFullscreen = allowFullscreen ?? true;
    }

    refreshFrame(): void {
        this.refreshToken = Date.now();
    }

    getFrameSource(): string {
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
}
