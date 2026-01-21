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
export declare class VimeoWidget extends VideoWidget {
    private showTitle;
    private showByline;
    private showPortrait;
    private color;
    constructor(opts: VimeoWidgetOptions);
    protected getProviderName(): string;
    protected parseVideoId(url: string): string | null;
    protected getEmbedUrl(videoId: string): string;
}
//# sourceMappingURL=vimeo-widget.d.ts.map