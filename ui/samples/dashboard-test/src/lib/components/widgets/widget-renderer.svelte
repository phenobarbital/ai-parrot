<script lang="ts">
    import type { Snippet } from "svelte";
    import type { Widget } from "../../domain/widget.svelte.js";
    import { FreeLayout } from "../../domain/layouts/free-layout.svelte.js";
    import { GridLayout } from "../../domain/layouts/grid-layout.svelte.js";
    import { IFrameWidget } from "../../domain/iframe-widget.svelte.js";
    import { ImageWidget } from "../../domain/image-widget.svelte.js";
    import ConfirmDialog from "../modals/confirm-dialog.svelte";
    import WidgetSettingsModal from "../modals/widget-settings-modal.svelte";

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

    // Toolbar buttons configuration
    const defaultButtons = $derived([
        {
            id: "minimize",
            icon: widget.minimized ? "▼" : "−",
            title: widget.minimized ? "Expand" : "Minimize",
            onClick: () => widget.toggleMinimize(),
            visible: () => widget.minimizable,
        },
        {
            id: "maximize",
            icon: "□",
            title: "Maximize",
            onClick: () => widget.maximize(),
            visible: () => !widget.isMaximized && widget.maximizable,
        },
        {
            id: "restore",
            icon: "❐",
            title: "Restore",
            onClick: () => widget.restore(),
            visible: () => widget.isMaximized,
        },
        {
            id: "float",
            icon: widget.isFloating ? "⊡" : "↗",
            title: widget.isFloating ? "Dock" : "Float",
            onClick: () => widget.toggleFloating(),
            visible: () => widget.floatable,
        },
        {
            id: "refresh",
            icon: "↻",
            title: "Refresh",
            onClick: () => widget.refresh(),
            visible: () => !!widget.config.onRefresh,
        },
        {
            id: "settings",
            icon: "⚙",
            title: "Settings",
            onClick: () => (showSettings = true),
            visible: () => true,
        },
        {
            id: "close",
            icon: "×",
            title: "Close",
            onClick: () => (showCloseConfirm = true),
            visible: () => widget.closable,
        },
    ]);

    // Combine default + custom buttons
    const allButtons = $derived([
        ...defaultButtons,
        ...widget.getToolbarButtons(),
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
                            {btn.icon}
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
                    ☰
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
            transform 0.2s;
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

    .widget:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
        border-color: var(--border-hover, #d1d5db);
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
        padding: 4px 10px;
        background: linear-gradient(to bottom, #f8f9fa, #e8eaed);
        border-bottom: 1px solid var(--border-subtle, #e8eaed);
        cursor: grab;
        user-select: none;
        flex-shrink: 0;
        min-height: 32px;
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
        font-size: 0.9rem;
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
        padding: 8px 12px;
        background: var(--surface-2, #f8f9fa);
        border-top: 1px solid var(--border-subtle, #f3f4f6);
        flex-shrink: 0;
    }

    /* STATUSBAR */
    .widget-statusbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 2px 8px;
        background: var(--surface-3, #f1f3f4);
        border-top: 1px solid var(--border-subtle, #e8eaed);
        font-size: 0.7rem;
        color: var(--text-3, #9aa0a6);
        min-height: 20px;
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
        bottom: 0;
        right: 0;
        width: 16px;
        height: 16px;
        cursor: nwse-resize;
        z-index: 50;
        background: linear-gradient(
                135deg,
                transparent 40%,
                var(--text-3, #9aa0a6) 40%,
                var(--text-3, #9aa0a6) 50%,
                transparent 50%
            ),
            linear-gradient(
                135deg,
                transparent 60%,
                var(--text-3, #9aa0a6) 60%,
                var(--text-3, #9aa0a6) 70%,
                transparent 70%
            ),
            linear-gradient(
                135deg,
                transparent 80%,
                var(--text-3, #9aa0a6) 80%,
                var(--text-3, #9aa0a6) 90%,
                transparent 90%
            );
        opacity: 0.8;
    }

    .resize-handle:hover {
        opacity: 1;
        background-color: rgba(0, 0, 0, 0.05);
    }
</style>
