import { UrlWidget, type UrlWidgetOptions } from "./url-widget.js";
import type { ConfigTab } from "./widget-config-modal.js";
export interface VideoWidgetOptions extends UrlWidgetOptions {
    autoplay?: boolean;
    controls?: boolean;
    loop?: boolean;
    muted?: boolean;
    startTime?: number;
}
/**
 * Abstract base class for video embedding widgets.
 * Subclasses: YouTubeWidget, VimeoWidget
 */
export declare abstract class VideoWidget extends UrlWidget {
    private _iframe;
    protected autoplay: boolean;
    protected controls: boolean;
    protected loop: boolean;
    protected muted: boolean;
    protected startTime: number;
    constructor(opts: VideoWidgetOptions);
    private initializeVideoElement;
    protected onInit(): void;
    /** Parse video ID from URL - implement in subclasses */
    protected abstract parseVideoId(url: string): string | null;
    /** Get the embed URL for the video - implement in subclasses */
    protected abstract getEmbedUrl(videoId: string): string;
    /** Get video provider name for display */
    protected abstract getProviderName(): string;
    protected updateContent(): void;
    /** Reload video from current URL */
    reload(): void;
    /** Override to add video config tab */
    getConfigTabs(): ConfigTab[];
    /** Apply video config on save */
    protected onConfigSave(config: Record<string, unknown>): void;
    /** Create the video configuration tab */
    protected createVideoConfigTab(): ConfigTab;
}
//# sourceMappingURL=video-widget.d.ts.map