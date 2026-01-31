import { VideoWidget, type VideoWidgetConfig } from "./video-widget.svelte.js";

export class YouTubeWidget extends VideoWidget {
    constructor(config: VideoWidgetConfig) {
        super({
            ...config,
            title: config.title || "YouTube Video",
            icon: config.icon ?? "📺",
        });
    }

    getEmbedUrl(): string {
        const source = this.getResolvedSource();
        if (!source) return "";

        // Simple ID extraction - could be improved with regex
        let id = source;
        if (source.includes("v=")) {
            id = source.split("v=")[1].split("&")[0];
        } else if (source.includes("youtu.be/")) {
            id = source.split("youtu.be/")[1];
        } else if (source.includes("/embed/")) {
            return source; // Already an embed URL?
        }

        // Construct embed URL with params
        const params = new URLSearchParams();
        if (this.autoplay) params.set("autoplay", "1");
        if (this.loop) params.set("loop", "1");
        if (this.muted) params.set("mute", "1");
        if (!this.controls) params.set("controls", "0");

        // Loop in youtube requires playlist param with same video ID
        if (this.loop) params.set("playlist", id);

        return `https://www.youtube.com/embed/${id}?${params.toString()}`;
    }
}
