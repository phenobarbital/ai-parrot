<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Widget } from '../../domain/widget.svelte.js';
    import { FreeLayout } from '../../domain/layouts/free-layout.svelte.js';
    import { ImageWidget } from '../../domain/image-widget.svelte.js';
    import { IFrameWidget } from '../../domain/iframe-widget.svelte.js';
    import { YouTubeWidget } from '../../domain/youtube-widget.svelte.js';
    import { VimeoWidget } from '../../domain/vimeo-widget.svelte.js';
    import { VideoWidget } from '../../domain/video-widget.svelte.js';
    import { PdfWidget } from '../../domain/pdf-widget.svelte.js';
    
    import WidgetTitlebar from './widget-titlebar.svelte';
    import WidgetContentRouter from './widget-content-router.svelte';
    import WidgetStatusbar from './widget-statusbar.svelte';
    import WidgetModals from './widget-modals.svelte';
    import LazyWidget from './LazyWidget.svelte';

    interface Props {
        widget: Widget;
        headerSlot?: Snippet;
        content?: Snippet;
        footerSlot?: Snippet;
        onResizeStart?: (e: PointerEvent) => void;
    }

    let { widget, headerSlot, content, footerSlot, onResizeStart }: Props = $props();

    // Modal state
    let showCloseConfirm = $state(false);
    let showSettings = $state(false);

    // Responsive toolbar state
    let showBurgerMenu = $state(false);
    let toolbarRef = $state<HTMLDivElement | null>(null);
    let isToolbarOverflowing = $state(false);

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

    // Combine custom and default buttons
    const visibleButtons = $derived(
        [
            ...widget.getToolbarButtons(),
            ...defaultButtons.filter((btn) => btn.id !== "close"),
            ...defaultButtons.filter((btn) => btn.id === "close"),
        ].filter((btn) => !btn.visible || btn.visible())
    );

    function handleGlobalClick() {
        if (showBurgerMenu) {
            showBurgerMenu = false;
        }
    }

    // Floating Drag functionality
    function handleTitlePointerDown(e: PointerEvent) {
        if (!widget.isFloating) return;

        e.stopPropagation();
        e.preventDefault();

        const widgetEl = (e.target as HTMLElement).closest(".widget") as HTMLElement;
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
        e.stopPropagation();
        e.preventDefault();

        if (onResizeStart && !widget.isFloating) {
            onResizeStart(e);
            return;
        }

        const widgetEl = (e.target as HTMLElement).closest(".widget") as HTMLElement;
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

    // Check if widget content is heavy to determine if we should use lazy loading
    // Images, iframes, videos are considered "heavy" by default
    const isHeavyContent = $derived(
        widget instanceof ImageWidget ||
        widget instanceof IFrameWidget ||
        widget instanceof YouTubeWidget ||
        widget instanceof VimeoWidget ||
        widget instanceof VideoWidget ||
        widget instanceof PdfWidget ||
        // Charts are also heavy
        widget.type.includes('chart') ||
        widget.type.includes('map')
    );
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
        <WidgetTitlebar
            {widget}
            {visibleButtons}
            bind:showBurgerMenu
            {isToolbarOverflowing}
            onDrag={handleTitlePointerDown}
            onBurgerToggle={(e) => {
                e.stopPropagation();
                showBurgerMenu = !showBurgerMenu;
            }}
            onBurgerAction={(action) => {
                action();
                showBurgerMenu = false;
            }}
        />
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
            {#if isHeavyContent}
                <LazyWidget>
                    <WidgetContentRouter {widget} {content} />
                </LazyWidget>
            {:else}
                <WidgetContentRouter {widget} {content} />
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
            <WidgetStatusbar {widget} {onResizeStart} />
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

<WidgetModals
    {widget}
    bind:showCloseConfirm
    bind:showSettings
    onConfirmClose={() => {
        showCloseConfirm = false;
        widget.close();
    }}
    onCancelClose={() => (showCloseConfirm = false)}
    onCloseSettings={() => (showSettings = false)}
/>

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

    /* FOOTER */
    .widget-footer {
        padding: 4px 8px;
        background: var(--surface-2, #f8f9fa);
        border-top: 1px solid var(--border-subtle, #f3f4f6);
        flex-shrink: 0;
        font-size: 0.75rem;
        color: var(--text-2, #5f6368);
    }
</style>
