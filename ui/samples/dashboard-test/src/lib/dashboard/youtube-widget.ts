// youtube-widget.ts - Widget for embedding YouTube videos
import { VideoWidget, type VideoWidgetOptions } from "./video-widget.js";

export interface YouTubeWidgetOptions extends VideoWidgetOptions {
    /** Show related videos at the end (default: false) */
    showRelated?: boolean;
}

/**
 * Widget that embeds a YouTube video.
 * Accepts YouTube URLs in various formats:
 * - https://www.youtube.com/watch?v=VIDEO_ID
 * - https://youtu.be/VIDEO_ID
 * - https://www.youtube.com/embed/VIDEO_ID
 */
export class YouTubeWidget extends VideoWidget {
    private showRelated: boolean = false;

    constructor(opts: YouTubeWidgetOptions) {
        super({
            icon: "📺",
            ...opts,
            title: opts.title || "YouTube Video",
            onRefresh: async () => this.reload(),
        });
        this.showRelated = opts.showRelated ?? false;
    }

    protected getProviderName(): string {
        return "YouTube";
    }

    protected parseVideoId(url: string): string | null {
        if (!url) return null;

        // Match various YouTube URL formats
        const patterns = [
            /(?:youtube\.com\/watch\?v=|youtube\.com\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})/,
            /^([a-zA-Z0-9_-]{11})$/, // Just the video ID
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
        if (!this.controls) params.set("controls", "0");
        if (this.loop) {
            params.set("loop", "1");
            params.set("playlist", videoId); // Required for loop to work
        }
        if (this.muted) params.set("mute", "1");
        if (this.startTime > 0) params.set("start", String(this.startTime));
        if (!this.showRelated) params.set("rel", "0");

        params.set("modestbranding", "1"); // Hide YouTube logo
        params.set("enablejsapi", "1"); // Enable JS API for future control

        const queryString = params.toString();
        return `https://www.youtube.com/embed/${videoId}${queryString ? "?" + queryString : ""}`;
    }
}
