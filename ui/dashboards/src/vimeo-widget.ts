// vimeo-widget.ts - Widget for embedding Vimeo videos
import { VideoWidget, type VideoWidgetOptions } from "./video-widget.js";

export interface VimeoWidgetOptions extends VideoWidgetOptions {
    /** Show video title (default: true) */
    showTitle?: boolean;
    /** Show video byline/author (default: true) */
    showByline?: boolean;
    /** Show video portrait/avatar (default: true) */
    showPortrait?: boolean;
    /** Accent color for player controls (hex without #) */
    color?: string;
}

/**
 * Widget that embeds a Vimeo video.
 * Accepts Vimeo URLs in various formats:
 * - https://vimeo.com/VIDEO_ID
 * - https://player.vimeo.com/video/VIDEO_ID
 */
export class VimeoWidget extends VideoWidget {
    private showTitle: boolean = true;
    private showByline: boolean = true;
    private showPortrait: boolean = true;
    private color: string = "";

    constructor(opts: VimeoWidgetOptions) {
        super({
            icon: "🎥",
            ...opts,
            title: opts.title || "Vimeo Video",
            onRefresh: async () => this.reload(),
        });
        this.showTitle = opts.showTitle ?? true;
        this.showByline = opts.showByline ?? true;
        this.showPortrait = opts.showPortrait ?? true;
        this.color = opts.color ?? "";
    }

    protected getProviderName(): string {
        return "Vimeo";
    }

    protected parseVideoId(url: string): string | null {
        if (!url) return null;

        // Match various Vimeo URL formats
        const patterns = [
            /vimeo\.com\/(\d+)/,
            /player\.vimeo\.com\/video\/(\d+)/,
            /^(\d+)$/, // Just the video ID
        ];

        for (const pattern of patterns) {
            const match = url.match(pattern);
            if (match?.[1]) {
                return match[1];
            }
        }

        return null;
    }

    protected getEmbedUrl(videoId: string): string {
        const params = new URLSearchParams();

        if (this.autoplay) params.set("autoplay", "1");
        if (this.loop) params.set("loop", "1");
        if (this.muted) params.set("muted", "1");
        if (!this.showTitle) params.set("title", "0");
        if (!this.showByline) params.set("byline", "0");
        if (!this.showPortrait) params.set("portrait", "0");
        if (this.color) params.set("color", this.color);

        // Vimeo uses #t= for start time in the hash, not query params
        let url = `https://player.vimeo.com/video/${videoId}`;
        const queryString = params.toString();
        if (queryString) url += "?" + queryString;
        if (this.startTime > 0) url += `#t=${this.startTime}s`;

        return url;
    }
}
