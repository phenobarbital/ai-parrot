import { VideoWidget, type VideoWidgetConfig } from "./video-widget.svelte.js";

export class VimeoWidget extends VideoWidget {
    constructor(config: VideoWidgetConfig) {
        super({
            ...config,
            title: config.title || "Vimeo Video",
            icon: config.icon ?? "🎥", // Using filtered icon
        });
    }

    getEmbedUrl(): string {
        const source = this.getResolvedSource();
        if (!source) return "";

        // Simple ID extraction
        let id = source;
        // Avoid "vimeo.com/" in regex logic if strictly numeric
        if (source.match(/^\d+$/)) {
            id = source;
        } else {
            const parts = source.split("/").filter(p => !!p && !p.includes("http") && !p.includes("vimeo.com"));
            // usually the last part is the id
            if (parts.length > 0) id = parts[parts.length - 1];
        }

        const params = new URLSearchParams();
        if (this.autoplay) params.set("autoplay", "1");
        if (this.loop) params.set("loop", "1");
        if (this.muted) params.set("muted", "1");
        // Vimeo controls: "controls" is not a standard param for iframe embed in the same way, usually implicit or 'background'
        // But for standard player, it's there.
        if (!this.controls) params.set("controls", "0");

        return `https://player.vimeo.com/video/${id}?${params.toString()}`;
    }
}
