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
export declare class YouTubeWidget extends VideoWidget {
    private showRelated;
    constructor(opts: YouTubeWidgetOptions);
    protected getProviderName(): string;
    protected parseVideoId(url: string): string | null;
    protected getEmbedUrl(videoId: string): string;
}
//# sourceMappingURL=youtube-widget.d.ts.map