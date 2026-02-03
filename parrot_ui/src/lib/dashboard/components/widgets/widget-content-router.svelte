<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Widget } from '../../domain/widget.svelte.js';
    import { IFrameWidget } from '../../domain/iframe-widget.svelte.js';
    import { ImageWidget } from '../../domain/image-widget.svelte.js';
    import { SimpleTableWidget } from '../../domain/simple-table-widget.svelte.js';
    import { TableWidget } from '../../domain/table-widget.svelte.js';
    import { EchartsWidget } from '../../domain/echarts-widget.svelte.js';
    import { VegaChartWidget } from '../../domain/vega-chart-widget.svelte.js';
    import { FrappeChartWidget } from '../../domain/frappe-chart-widget.svelte.js';
    import { CarbonChartsWidget } from '../../domain/carbon-charts-widget.svelte.js';
    import { LayerChartWidget } from '../../domain/layer-chart-widget.svelte.js';
    import { BasicChartWidget } from '../../domain/basic-chart-widget.svelte.js';
    import { MapWidget } from '../../domain/map-widget.svelte.js';
    import { VideoWidget } from '../../domain/video-widget.svelte.js';
    import { YouTubeWidget } from '../../domain/youtube-widget.svelte.js';
    import { VimeoWidget } from '../../domain/vimeo-widget.svelte.js';
    import { PdfWidget } from '../../domain/pdf-widget.svelte.js';
    import { HtmlWidget } from '../../domain/html-widget.svelte.js';
    import { MarkdownWidget } from '../../domain/markdown-widget.svelte.js';
    import { marked } from 'marked';
    import SimpleTableContent from './SimpleTableContent.svelte';
    import TableWidgetContent from './TableWidgetContent.svelte';
    import EchartsWidgetContent from './echarts-widget-content.svelte';
    import VegaWidgetContent from './vega-widget-content.svelte';
    import FrappeWidgetContent from './frappe-widget-content.svelte';
    import CarbonWidgetContent from './carbon-widget-content.svelte';
    import LayerChartWidgetContent from './layer-chart-widget-content.svelte';
    import MapWidgetContent from './map-widget-content.svelte';

    interface Props {
        widget: Widget;
        content?: Snippet;
        onCopy?: (text: string) => void;
    }

    let { widget, content, onCopy }: Props = $props();

    async function copyToClipboard(text: string) {
        try {
            await navigator.clipboard.writeText(text);
            onCopy?.(text);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    }
</script>

{#if widget.loading}
    <div class="widget-loading">
        <span class="spinner"></span>
        Loading...
    </div>
{:else if widget.error}
    <div class="widget-error">⚠️ {widget.error}</div>
{:else if content}
    {@render content()}
{:else if widget instanceof ImageWidget}
    {@const source = widget.getImageSource()}
    {#if source}
        <img
            class="widget-media"
            src={source}
            alt={widget.altText}
            style:object-fit={widget.objectFit}
        />
    {:else}
        <div class="widget-empty">No image configured</div>
    {/if}
{:else if widget instanceof IFrameWidget}
    {@const source = widget.getFrameSource()}
    {#if source}
        <iframe
            class="widget-media"
            src={source}
            title={widget.title}
            sandbox={widget.sandboxAttr}
            allowfullscreen={widget.allowFullscreen}
        ></iframe>
    {:else}
        <div class="widget-empty">No URL configured</div>
    {/if}
{:else if widget instanceof YouTubeWidget}
    {@const embedUrl = widget.getEmbedUrl()}
    {#if embedUrl}
        <iframe
            class="widget-media"
            src={embedUrl}
            title={widget.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen
        ></iframe>
    {:else}
        <div class="widget-empty">No YouTube URL configured</div>
    {/if}
{:else if widget instanceof VimeoWidget}
    {@const embedUrl = widget.getEmbedUrl()}
    {#if embedUrl}
        <iframe
            class="widget-media"
            src={embedUrl}
            title={widget.title}
            allow="autoplay; fullscreen; picture-in-picture"
            allowfullscreen
        ></iframe>
    {:else}
        <div class="widget-empty">No Vimeo URL configured</div>
    {/if}
{:else if widget instanceof VideoWidget}
    {@const source = widget.getResolvedSource()}
    {#if source}
        <video
            class="widget-media"
            src={source}
            controls={widget.controls}
            autoplay={widget.autoplay}
            loop={widget.loop}
            muted={widget.muted}
        >
            <track kind="captions" />
            Your browser does not support the video element.
        </video>
    {:else}
        <div class="widget-empty">No video URL configured</div>
    {/if}
{:else if widget instanceof PdfWidget}
    {@const pdfUrl = widget.getPdfUrl()}
    {#if pdfUrl}
        <iframe
            class="widget-media pdf-viewer"
            src={pdfUrl}
            title={widget.title}
        ></iframe>
    {:else}
        <div class="widget-empty">No PDF URL configured</div>
    {/if}
{:else if widget instanceof MarkdownWidget}
    {#if widget.content}
        <div class="widget-content-with-copy">
            <button
                class="copy-btn"
                title="Copy to clipboard"
                onclick={() => copyToClipboard(widget.content)}
            >
                📋
            </button>
            <div class="widget-markdown">
                {@html marked.parse(widget.content)}
            </div>
        </div>
    {:else}
        <div class="widget-empty">No markdown content</div>
    {/if}
{:else if widget instanceof HtmlWidget}
    {#if widget.content}
        <div class="widget-content-with-copy">
            <button
                class="copy-btn"
                title="Copy to clipboard"
                onclick={() => copyToClipboard(widget.content)}
            >
                📋
            </button>
            <div class="widget-html">{@html widget.content}</div>
        </div>
    {:else}
        <div class="widget-empty">No HTML content</div>
    {/if}
{:else if widget instanceof SimpleTableWidget}
    <SimpleTableContent {widget} />
{:else if widget instanceof TableWidget}
    <TableWidgetContent {widget} />
{:else if widget instanceof EchartsWidget}
    <EchartsWidgetContent {widget} />
{:else if widget instanceof VegaChartWidget}
    <VegaWidgetContent {widget} />
{:else if widget instanceof FrappeChartWidget}
    <FrappeWidgetContent {widget} />
{:else if widget instanceof CarbonChartsWidget}
    <CarbonWidgetContent {widget} />
{:else if widget instanceof LayerChartWidget}
    <LayerChartWidgetContent {widget} />
{:else if widget instanceof BasicChartWidget}
    {#if widget.chartEngine === 'echarts'}
        <EchartsWidgetContent {widget} />
    {:else if widget.chartEngine === 'vega'}
        <VegaWidgetContent {widget} />
    {:else if widget.chartEngine === 'frappe'}
        <FrappeWidgetContent {widget} />
    {:else}
        <CarbonWidgetContent {widget} />
    {/if}
{:else if widget instanceof MapWidget}
    <MapWidgetContent {widget} />
{:else}
    <div class="widget-empty">No content</div>
{/if}

<style>
    .widget-media {
        width: 100%;
        height: 100%;
        border: none;
        display: block;
    }

    .widget-loading {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        height: 100%;
        color: var(--text-2, #5f6368);
        font-size: 0.9rem;
    }

    .spinner {
        width: 16px;
        height: 16px;
        border: 2px solid var(--border, #e8eaed);
        border-top-color: var(--primary, #1a73e8);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    .widget-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--text-3, #9aa0a6);
        font-size: 0.9rem;
    }

    .widget-error {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--danger, #dc3545);
        font-size: 0.9rem;
        padding: 16px;
        text-align: center;
    }

    .widget-content-with-copy {
        position: relative;
        height: 100%;
        overflow: auto;
    }

    .copy-btn {
        position: absolute;
        top: 0.5rem;
        right: 0.5rem;
        padding: 0.25rem 0.5rem;
        border: 1px solid var(--border, #ddd);
        border-radius: 4px;
        background: var(--surface, #fff);
        cursor: pointer;
        opacity: 0;
        transition: opacity 0.2s;
        z-index: 10;
        font-size: 0.9rem;
    }

    .widget-content-with-copy:hover .copy-btn {
        opacity: 0.7;
    }

    .copy-btn:hover {
        opacity: 1 !important;
        background: var(--hover, #f0f0f0);
    }

    .widget-html,
    .widget-markdown {
        padding: 1rem;
        height: 100%;
        overflow: auto;
    }
</style>
