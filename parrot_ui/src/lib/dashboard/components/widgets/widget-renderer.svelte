<script lang="ts">
    import type { Snippet } from "svelte";
    import type { Widget } from "../../domain/widget.svelte.js";
    import { FreeLayout } from "../../domain/layouts/free-layout.svelte.js";
    import { GridLayout } from "../../domain/layouts/grid-layout.svelte.js";
    import { IFrameWidget } from "../../domain/iframe-widget.svelte.js";
    import { ImageWidget } from "../../domain/image-widget.svelte.js";
    import { SimpleTableWidget } from "../../domain/simple-table-widget.svelte.js";
    import { TableWidget } from "../../domain/table-widget.svelte.js";
    import { EchartsWidget } from "../../domain/echarts-widget.svelte.js";
    import { VegaChartWidget } from "../../domain/vega-chart-widget.svelte.js";
    import { FrappeChartWidget } from "../../domain/frappe-chart-widget.svelte.js";
    import { CarbonChartsWidget } from "../../domain/carbon-charts-widget.svelte.js";
    import { LayerChartWidget } from "../../domain/layer-chart-widget.svelte.js";
    import { BasicChartWidget } from "../../domain/basic-chart-widget.svelte.js";
    import { MapWidget } from "../../domain/map-widget.svelte.js";
    import { VideoWidget } from "../../domain/video-widget.svelte.js";
    import { YouTubeWidget } from "../../domain/youtube-widget.svelte.js";
    import { VimeoWidget } from "../../domain/vimeo-widget.svelte.js";
    import { PdfWidget } from "../../domain/pdf-widget.svelte.js";
    import { HtmlWidget } from "../../domain/html-widget.svelte.js";
    import { MarkdownWidget } from "../../domain/markdown-widget.svelte.js";
    import { marked } from "marked";
    import ConfirmDialog from "../modals/confirm-dialog.svelte";
    import WidgetSettingsModal from "../modals/widget-settings-modal.svelte";
    import SimpleTableContent from "./SimpleTableContent.svelte";
    import TableWidgetContent from "./TableWidgetContent.svelte";
    import EchartsWidgetContent from "./echarts-widget-content.svelte";
    import VegaWidgetContent from "./vega-widget-content.svelte";
    import FrappeWidgetContent from "./frappe-widget-content.svelte";
    import CarbonWidgetContent from "./carbon-widget-content.svelte";
    import LayerChartWidgetContent from "./layer-chart-widget-content.svelte";
    import MapWidgetContent from "./map-widget-content.svelte";

    interface Props {
        widget: Widget;
        headerSlot?: Snippet;
        content?: Snippet;
        footerSlot?: Snippet;
        onResizeStart?: (e: PointerEvent) => void;
    }

    let { widget, headerSlot, content, footerSlot, onResizeStart }: Props =
        $props();

    // Modal state
    let showCloseConfirm = $state(false);
    let showSettings = $state(false);

    // Responsive toolbar state
    let showBurgerMenu = $state(false);
    let toolbarRef = $state<HTMLDivElement | null>(null);
    let isToolbarOverflowing = $state(false);

    // Copy to clipboard function
    async function copyToClipboard(text: string) {
        try {
            await navigator.clipboard.writeText(text);
            // Could add toast notification here
        } catch (err) {
            console.error("Failed to copy:", err);
        }
    }

    // Toolbar buttons configuration
    const defaultButtons = $derived([
        {
            id: "minimize",
            icon: widget.minimized
                ? '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>'
                : '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
            title: widget.minimized ? "Expand" : "Minimize",
            onClick: () => widget.toggleMinimize(),
            visible: () => widget.minimizable,
        },
        {
            id: "maximize",
            icon: '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>',
            title: "Maximize",
            onClick: () => widget.maximize(),
            visible: () => !widget.isMaximized && widget.maximizable,
        },
        {
            id: "restore",
            icon: '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><path d="M7 7h10v10"></path></svg>',
            title: "Restore",
            onClick: () => widget.restore(),
            visible: () => widget.isMaximized,
        },
        {
            id: "float",
            icon: widget.isFloating
                ? '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"></path><path d="M10 14L21 3"></path><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path></svg>'
                : '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"></path><path d="M10 14L21 3"></path><path d="M14 20H21"></path></svg>',
            title: widget.isFloating ? "Dock" : "Float",
            onClick: () => widget.toggleFloating(),
            visible: () => widget.floatable,
        },
        {
            id: "refresh",
            icon: '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>',
            title: "Refresh",
            onClick: () => widget.refresh(),
            visible: () => !!widget.config.onRefresh,
        },
        {
            id: "settings",
            icon: '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>',
            title: "Settings",
            onClick: () => (showSettings = true),
            visible: () => true,
        },
        {
            id: "close",
            icon: '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
            title: "Close",
            onClick: () => (showCloseConfirm = true),
            visible: () => widget.closable,
        },
    ]);

    // Combine: custom buttons + default buttons (close always last)
    const allButtons = $derived([
        ...widget.getToolbarButtons(),
        ...defaultButtons.filter((btn) => btn.id !== "close"),
        ...defaultButtons.filter((btn) => btn.id === "close"),
    ]);

    // Visible buttons
    const visibleButtons = $derived(
        allButtons.filter((btn) => !btn.visible || btn.visible()),
    );

    function handleConfirmClose() {
        showCloseConfirm = false;
        widget.close();
    }

    function handleCancelClose() {
        showCloseConfirm = false;
    }

    function toggleBurgerMenu(e: MouseEvent) {
        e.stopPropagation();
        showBurgerMenu = !showBurgerMenu;
    }

    function handleBurgerAction(action: () => void) {
        action();
        showBurgerMenu = false;
    }

    // Close burger menu on outside click
    function handleGlobalClick() {
        if (showBurgerMenu) {
            showBurgerMenu = false;
        }
    }

    // Resize functionality
    // Resize functionality
    // Floating Drag functionality
    function handleTitlePointerDown(e: PointerEvent) {
        if (!widget.isFloating) return;

        // Stop grid/parent from seeing this event
        e.stopPropagation();
        e.preventDefault();

        const widgetEl = (e.target as HTMLElement).closest(
            ".widget",
        ) as HTMLElement;
        if (!widgetEl) return;

        const startX = e.clientX;
        const startY = e.clientY;
        const startLeft = parseFloat(widgetEl.style.left || "100");
        const startTop = parseFloat(widgetEl.style.top || "100");

        (e.target as HTMLElement).setPointerCapture(e.pointerId);

        const onMove = (moveEvent: PointerEvent) => {
            const dx = moveEvent.clientX - startX;
            const dy = moveEvent.clientY - startY;

            widgetEl.style.left = `${startLeft + dx}px`;
            widgetEl.style.top = `${startTop + dy}px`;
        };

        const onUp = (upEvent: PointerEvent) => {
            (e.target as HTMLElement).releasePointerCapture(upEvent.pointerId);
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);

            // Save new position
            widget.setFloatingStyles({
                left: widgetEl.style.left,
                top: widgetEl.style.top,
                width: widgetEl.style.width,
                height: widgetEl.style.height,
            });
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    // Resize functionality
    function handleResizeStart(e: PointerEvent) {
        // Prevent default drag
        e.stopPropagation();
        e.preventDefault();

        console.log("[WidgetRenderer] handleResizeStart", {
            widgetId: widget.id,
            isFloating: widget.isFloating,
        });

        if (onResizeStart && !widget.isFloating) {
            onResizeStart(e);
            return;
        }

        const widgetEl = (e.target as HTMLElement).closest(
            ".widget",
        ) as HTMLElement;
        if (!widgetEl) return;

        const startX = e.clientX;
        const startY = e.clientY;
        const startWidth = widgetEl.offsetWidth;
        const startHeight = widgetEl.offsetHeight;

        const layout = widget.tab?.layout;
        const isFreeLayout = layout instanceof FreeLayout;

        if (!widget.isFloating && isFreeLayout) {
            layout.startResize(widget.id, "se", e.clientX, e.clientY);
        }

        (e.target as HTMLElement).setPointerCapture(e.pointerId);

        const onMove = (moveEvent: PointerEvent) => {
            const dx = moveEvent.clientX - startX;
            const dy = moveEvent.clientY - startY;

            if (widget.isFloating) {
                const newWidth = Math.max(200, startWidth + dx);
                const newHeight = Math.max(150, startHeight + dy);
                widgetEl.style.width = `${newWidth}px`;
                widgetEl.style.height = `${newHeight}px`;
            } else if (isFreeLayout) {
                layout.updateResize(moveEvent.clientX, moveEvent.clientY);
            }
        };

        const onUp = (upEvent: PointerEvent) => {
            (e.target as HTMLElement).releasePointerCapture(upEvent.pointerId);
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            if (widget.isFloating) {
                widget.setFloatingStyles({
                    left: widgetEl.style.left,
                    top: widgetEl.style.top,
                    width: widgetEl.style.width,
                    height: widgetEl.style.height,
                });
            } else if (isFreeLayout) {
                layout.endResize();
            }
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }
</script>

<svelte:window onclick={handleGlobalClick} />

<article
    class="widget"
    class:minimized={widget.minimized}
    class:floating={widget.isFloating}
    class:maximized={widget.isMaximized}
    class:loading={widget.loading}
    class:chrome-hidden={widget.chromeHidden}
    class:translucent={widget.translucent}
    data-widget-id={widget.id}
    data-mode={widget.mode}
    style={widget.isFloating
        ? `left:${widget.getFloatingStyles()?.left};top:${widget.getFloatingStyles()?.top};width:${widget.getFloatingStyles()?.width};height:${widget.getFloatingStyles()?.height};`
        : ""}
>
    <!-- TITLEBAR -->
    {#if !widget.chromeHidden}
        <header
            class="widget-titlebar"
            style:background={widget.getTitleBarGradient()}
            onpointerdown={handleTitlePointerDown}
        >
            <div class="widget-title-group">
                <span class="widget-icon" style:color={widget.titleColor}
                    >{widget.icon}</span
                >
                <h3 class="widget-title" style:color={widget.titleColor}>
                    {widget.title}
                </h3>
            </div>

            <div class="widget-actions">
                <!-- Regular toolbar (hidden when overflowing) -->
                <div
                    class="widget-toolbar"
                    bind:this={toolbarRef}
                    class:hidden={isToolbarOverflowing}
                >
                    {#each visibleButtons as btn (btn.id)}
                        <button
                            class="widget-toolbtn"
                            class:close-btn={btn.id === "close"}
                            class:settings-btn={btn.id === "settings"}
                            type="button"
                            title={btn.title}
                            onclick={(e) => {
                                e.stopPropagation();
                                btn.onClick();
                            }}
                        >
                            {@html btn.icon}
                        </button>
                    {/each}
                </div>

                <!-- Burger menu button -->
                <button
                    class="widget-burger"
                    type="button"
                    title="Menu"
                    onclick={toggleBurgerMenu}
                >
                    <svg
                        class="w-3.5 h-3.5"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        ><line x1="3" y1="12" x2="21" y2="12"></line><line
                            x1="3"
                            y1="6"
                            x2="21"
                            y2="6"
                        ></line><line x1="3" y1="18" x2="21" y2="18"></line></svg
                    >
                </button>

                <!-- Burger dropdown menu -->
                {#if showBurgerMenu}
                    <div
                        class="burger-menu"
                        onclick={(e) => e.stopPropagation()}
                    >
                        {#each visibleButtons as btn (btn.id)}
                            <button
                                class="burger-item"
                                class:danger={btn.id === "close"}
                                type="button"
                                onclick={() => handleBurgerAction(btn.onClick)}
                            >
                                <span class="burger-icon">{btn.icon}</span>
                                <span class="burger-label">{btn.title}</span>
                            </button>
                        {/each}
                    </div>
                {/if}
            </div>
        </header>
    {/if}

    {#if !widget.minimized}
        <!-- HEADER (optional) -->
        {#if headerSlot || widget.headerContent}
            <div class="widget-header">
                {#if headerSlot}
                    {@render headerSlot()}
                {:else if widget.headerContent}
                    {@html widget.headerContent}
                {/if}
            </div>
        {/if}

        <!-- CONTENT -->
        <div
            class="widget-content"
            class:chrome-drag={widget.chromeHidden}
            onpointerdown={widget.chromeHidden ? handleTitlePointerDown : null}
        >
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
                {#if widget.chartEngine === "echarts"}
                    <EchartsWidgetContent {widget} />
                {:else if widget.chartEngine === "vega"}
                    <VegaWidgetContent {widget} />
                {:else if widget.chartEngine === "frappe"}
                    <FrappeWidgetContent {widget} />
                {:else}
                    <CarbonWidgetContent {widget} />
                {/if}
            {:else if widget instanceof MapWidget}
                <MapWidgetContent {widget} />
            {:else}
                <div class="widget-empty">No content</div>
            {/if}
        </div>

        <!-- FOOTER (optional) -->
        {#if footerSlot || widget.footerContent}
            <div class="widget-footer">
                {#if footerSlot}
                    {@render footerSlot()}
                {:else if widget.footerContent}
                    {@html widget.footerContent}
                {/if}
            </div>
        {/if}

        <!-- STATUSBAR -->
        {#if !widget.chromeHidden}
            <div class="widget-statusbar">
                <span class="status-message">{widget.statusMessage}</span>
                {#if widget.resizable}
                    <div
                        class="resize-handle"
                        title="Resize"
                        role="separator"
                        tabindex="-1"
                        onpointerdown={handleResizeStart}
                    ></div>
                {/if}
            </div>
        {/if}
    {/if}

    {#if widget.chromeHidden}
        <button
            class="ghost-settings"
            title="Settings"
            onclick={(e) => {
                e.stopPropagation();
                showSettings = true;
            }}
        >
            ⚙
        </button>
    {/if}
</article>

<!-- Modals -->
{#if showCloseConfirm}
    <ConfirmDialog
        title="Close Widget"
        message="Are you sure you want to close this widget?"
        confirmText="Close"
        cancelText="Cancel"
        type="warning"
        onConfirm={handleConfirmClose}
        onCancel={handleCancelClose}
    />
{/if}

{#if showSettings}
    <WidgetSettingsModal {widget} onClose={() => (showSettings = false)} />
{/if}

<style>
    .widget {
        display: flex;
        flex-direction: column;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #e5e7eb);
        border-radius: 8px;
        overflow: hidden;
        height: 100%;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
        transition:
            box-shadow 0.2s,
            border-color 0.2s,
            transform 0.2s,
            z-index 0s;
        position: relative;
    }

    .widget:hover {
        z-index: 10;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
        border-color: var(--border-hover, #d1d5db);
    }
    .widget.translucent {
        background: rgba(255, 255, 255, 0.82);
        backdrop-filter: blur(10px);
    }

    .widget.chrome-hidden .widget-content {
        cursor: grab;
    }

    .widget.chrome-hidden .widget-content:active {
        cursor: grabbing;
    }

    .widget.chrome-hidden .ghost-settings {
        position: absolute;
        top: 8px;
        right: 8px;
        border: none;
        background: rgba(255, 255, 255, 0.9);
        border-radius: 6px;
        width: 28px;
        height: 28px;
        display: grid;
        place-items: center;
        color: var(--text-2, #5f6368);
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
        opacity: 0;
        transition: opacity 120ms ease;
        cursor: pointer;
    }

    .widget.chrome-hidden:hover .ghost-settings,
    .widget.chrome-hidden:focus-within .ghost-settings {
        opacity: 1;
    }

    .widget.minimized {
        height: auto;
        min-height: 0;
    }

    .widget.floating {
        position: fixed;
        z-index: 1000;
        border: 2px solid var(--primary, #1a73e8);
        box-shadow: 0 8px 30px rgba(26, 115, 232, 0.25);
    }

    .widget.maximized {
        position: fixed !important;
        inset: 0 !important;
        z-index: 9999 !important;
        border-radius: 0;
        width: 100vw !important;
        height: 100vh !important;
    }

    /* TITLEBAR */
    .widget-titlebar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 2px 8px;
        background: linear-gradient(to bottom, #f8f9fa, #e8eaed);
        border-bottom: 1px solid var(--border-subtle, #e8eaed);
        cursor: grab;
        user-select: none;
        flex-shrink: 0;
        min-height: 24px;
    }

    .widget-titlebar:active {
        cursor: grabbing;
    }

    .widget-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
        overflow: hidden;
        flex: 1;
    }

    .widget-icon {
        font-size: 1.1rem;
        flex-shrink: 0;
    }

    .widget-title {
        margin: 0;
        font-size: 0.85rem;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .widget-actions {
        display: flex;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
        position: relative;
    }

    .widget-toolbar {
        display: flex;
        gap: 2px;
    }

    .widget-toolbar.hidden {
        display: none;
    }

    .widget-toolbtn {
        width: 26px;
        height: 26px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        color: var(--text-2, #5f6368);
        font-size: 0.95rem;
        transition:
            background 0.15s,
            color 0.15s;
    }

    .widget-toolbtn:hover {
        background: rgba(0, 0, 0, 0.08);
        color: var(--text, #202124);
    }

    .widget-toolbtn.close-btn:hover {
        background: rgba(220, 53, 69, 0.12);
        color: var(--danger, #dc3545);
    }

    .widget.chrome-hidden .widget-toolbtn.settings-btn {
        opacity: 0;
        pointer-events: none;
    }

    .widget-burger {
        width: 28px;
        height: 28px;
        display: none;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        color: var(--text-2, #5f6368);
        font-size: 1rem;
    }

    .widget-burger:hover {
        background: rgba(0, 0, 0, 0.08);
    }

    /* Responsive: show burger when toolbar would overflow */
    @container (max-width: 280px) {
        .widget-toolbar {
            display: none;
        }
        .widget-burger {
            display: flex;
        }
    }

    /* Fallback for browsers without container queries */
    @media (max-width: 400px) {
        .widget-toolbar {
            display: none;
        }
        .widget-burger {
            display: flex;
        }
    }

    .burger-menu {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #e8eaed);
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
        min-width: 160px;
        z-index: 1000;
        overflow: hidden;
    }

    .burger-item {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 10px 14px;
        background: transparent;
        border: none;
        text-align: left;
        cursor: pointer;
        color: var(--text, #202124);
        font-size: 0.875rem;
        transition: background 0.1s;
    }

    .burger-item:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .burger-item.danger:hover {
        background: rgba(220, 53, 69, 0.08);
        color: var(--danger, #dc3545);
    }

    .burger-icon {
        width: 20px;
        text-align: center;
    }

    /* HEADER */
    .widget-header {
        padding: 8px 12px;
        background: var(--surface-2, #f8f9fa);
        border-bottom: 1px solid var(--border-subtle, #f3f4f6);
        flex-shrink: 0;
    }

    /* CONTENT */
    .widget-content {
        flex: 1;
        overflow: auto;
        padding: 0;
        position: relative;
        background: var(--surface, #fff);
    }

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

    /* FOOTER */
    .widget-footer {
        padding: 4px 8px;
        background: var(--surface-2, #f8f9fa);
        border-top: 1px solid var(--border-subtle, #f3f4f6);
        flex-shrink: 0;
        font-size: 0.75rem;
        color: var(--text-2, #5f6368);
    }

    /* STATUSBAR */
    .widget-statusbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 8px;
        background: var(--surface-3, #f1f3f4);
        border-top: 1px solid var(--border-subtle, #e8eaed);
        font-size: 11px;
        color: var(--text-3, #9aa0a6);
        min-height: 18px;
        flex-shrink: 0;
    }

    .status-message {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .resize-handle {
        position: absolute;
        bottom: 0px;
        right: 0px;
        width: 12px;
        height: 12px;
        cursor: nwse-resize;
        z-index: 60;
        background: linear-gradient(
                135deg,
                transparent 45%,
                var(--text-3, #9aa0a6) 45%,
                var(--text-3, #9aa0a6) 55%,
                transparent 55%
            ),
            linear-gradient(
                135deg,
                transparent 65%,
                var(--text-3, #9aa0a6) 65%,
                var(--text-3, #9aa0a6) 75%,
                transparent 75%
            );
        opacity: 0.8;
        pointer-events: auto;
    }

    .resize-handle:hover {
        opacity: 1;
        background-color: rgba(0, 0, 0, 0.05);
        border-radius: 2px;
    }

    /* Copy to clipboard button */
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
