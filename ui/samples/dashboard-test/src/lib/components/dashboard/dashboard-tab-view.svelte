<script lang="ts">
    import type { DashboardTab as DashboardTabClass } from "../../domain/dashboard-tab.svelte.js";
    import { GridLayout } from "../../domain/layouts/grid-layout.svelte.js";
    import { FreeLayout } from "../../domain/layouts/free-layout.svelte.js";
    import { DockLayout } from "../../domain/layouts/dock-layout.svelte.js";
    import GridLayoutComponent from "../layouts/grid-layout.svelte";
    import FreeLayoutComponent from "../layouts/free-layout.svelte";
    import DockLayoutComponent from "../layouts/dock-layout.svelte";
    import WidgetRenderer from "../widgets/widget-renderer.svelte";
    import { getComponent } from "../../domain/component-registry.js";
    import { fade, crossfade } from "svelte/transition";
    import { quartOut } from "svelte/easing";

    interface Props {
        tab: DashboardTabClass;
    }

    let { tab }: Props = $props();

    // Template class for CSS
    let templateClass = $derived(`template-${tab.template}`);

    // Check if pane should be visible (has widgets or template is not default)
    let showPane = $derived(
        tab.template !== "default" && tab.layoutMode !== "component",
    );

    // Get component for component layout mode
    let ModuleComponent = $derived(
        tab.component ? getComponent(tab.component) : null,
    );

    // Pane style based on template
    function getPaneStyle(): string {
        if (tab.template === "default" || tab.layoutMode === "component") {
            return "height: 0; overflow: hidden; display: none;";
        }

        if (tab.template === "pane-left" || tab.template === "pane-right") {
            return `width: ${tab.paneSize}px; min-width: ${tab.paneSize}px;`;
        }
        if (tab.template === "pane-top" || tab.template === "pane-bottom") {
            return `height: ${tab.paneSize}px; min-height: ${tab.paneSize}px;`;
        }
        return "";
    }

    // Layout type casting for template
    let freeLayout = $derived(tab.layout as unknown as FreeLayout);
    let dockLayout = $derived(tab.layout as unknown as DockLayout);
    let gridLayout = $derived(tab.layout as unknown as GridLayout);

    // Slideshow Logic
    let slideshowWidget = $derived.by(() => {
        if (!tab.slideshowState.active) return null;
        const widgetId = tab.slideshowState.widgets[tab.slideshowState.index];
        if (!widgetId) return null;
        return tab.layout.getWidget(widgetId);
    });
    let slideshowOverlay = $state<HTMLDivElement | null>(null);

    function handleKeydown(e: KeyboardEvent) {
        if (!tab.slideshowState.active) return;

        console.log("[Slideshow] Keydown:", e.key);

        switch (e.key) {
            case "ArrowRight":
            case " ":
                tab.slideshowNext();
                break;
            case "ArrowLeft":
                tab.slideshowPrev();
                break;
            case "Escape":
                console.log("[Slideshow] Escape pressed");
                tab.exitSlideshow();
                break;
        }
    }

    function handleClose() {
        console.log("[Slideshow] Close clicked");
        tab.exitSlideshow();
    }

    $effect(() => {
        if (tab.slideshowState.active) {
            slideshowOverlay?.focus();
        }

        if (!tab.slideshowState.active || !tab.slideshowState.isPlaying) return;

        const intervalId = setInterval(() => {
            if (
                tab.slideshowState.index ===
                tab.slideshowState.widgets.length - 1
            ) {
                // Auto-pause at the end
                tab.toggleSlideshowPlay();
                return;
            }
            tab.slideshowNext();
        }, tab.slideshowState.interval);

        return () => clearInterval(intervalId);
    });
</script>

<svelte:window onkeydown={handleKeydown} />

<div
    class="dashboard-tab-view {templateClass}"
    class:component-mode={tab.layoutMode === "component"}
>
    <!-- Slideshow Overlay -->
    {#if tab.slideshowState.active && slideshowWidget}
        <div
            class="slideshow-overlay"
            transition:fade={{ duration: 200 }}
            tabindex="-1"
            role="dialog"
            aria-modal="true"
            aria-label="Slideshow"
            bind:this={slideshowOverlay}
            onkeydown={handleKeydown}
        >
            <!-- Content Container -->
            <div class="slideshow-content" transition:fade={{ duration: 300 }}>
                {#key slideshowWidget?.id}
                    <div
                        class="slideshow-frame"
                        in:fade={{ duration: 400 }}
                        out:fade={{ duration: 200 }}
                    >
                        <div class="widget-wrapper">
                            <WidgetRenderer widget={slideshowWidget} />
                        </div>
                    </div>
                {/key}
            </div>

            <!-- Controls Bar -->
            <div class="controls-container">
                <div class="controls-bar">
                    <button
                        class="control-btn"
                        onclick={() => tab.slideshowPrev()}
                        title="Previous"
                    >
                        ‹
                    </button>

                    <button
                        class="control-btn"
                        onclick={() => tab.toggleSlideshowPlay()}
                        title={tab.slideshowState.isPlaying ? "Pause" : "Play"}
                    >
                        {tab.slideshowState.isPlaying ? "⏸" : "▶"}
                    </button>

                    <div class="interval-input">
                        <span class="label">⏱</span>
                        <input
                            type="number"
                            value={tab.slideshowState.interval / 1000}
                            onchange={(e) =>
                                tab.setSlideshowInterval(
                                    e.currentTarget.valueAsNumber * 1000,
                                )}
                            min="1"
                            max="60"
                            step="0.5"
                        />
                        <span class="unit">s</span>
                    </div>

                    <div class="separator"></div>

                    <div class="progress-info">
                        Slide {tab.slideshowState.index + 1} of {tab
                            .slideshowState.widgets.length}
                    </div>

                    <div class="separator"></div>

                    <button
                        class="control-btn"
                        onclick={() => tab.slideshowNext()}
                        title="Next"
                    >
                        ›
                    </button>

                    <div class="separator"></div>

                    <button
                        class="control-btn danger"
                        onclick={handleClose}
                        title="Exit Slideshow (Esc)"
                    >
                        ×
                    </button>
                </div>

                {#if tab.slideshowState.index === tab.slideshowState.widgets.length - 1}
                    <div class="end-message" transition:fade>
                        End of Slideshow
                    </div>
                {/if}
            </div>
        </div>
    {/if}

    {#if tab.layoutMode === "component"}
        <!-- Component Layout Mode: render full module component -->
        <main class="dashboard-content component-content">
            {#if ModuleComponent}
                <ModuleComponent />
            {:else}
                <div class="component-missing">
                    <span class="missing-icon">⚠️</span>
                    <p>Component "{tab.component}" not found in registry</p>
                </div>
            {/if}
        </main>
    {:else if tab.template === "pane-top" || tab.template === "default"}
        <aside class="dashboard-pane" style={getPaneStyle()}>
            {#if showPane && tab.paneWidgets.length > 0}
                <div class="pane-widgets">
                    {#each tab.paneWidgets as widget (widget.id)}
                        <WidgetRenderer {widget} />
                    {/each}
                </div>
            {:else if showPane}
                <div class="pane-empty">
                    <span class="empty-text">Drop widgets here</span>
                </div>
            {/if}
        </aside>
        <main class="dashboard-content">
            {#if tab.layoutMode === "free"}
                <FreeLayoutComponent layout={freeLayout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={dockLayout} />
            {:else}
                <GridLayoutComponent layout={gridLayout} />
            {/if}
        </main>
    {:else if tab.template === "pane-bottom"}
        <main class="dashboard-content">
            {#if tab.layoutMode === "free"}
                <FreeLayoutComponent layout={freeLayout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={dockLayout} />
            {:else}
                <GridLayoutComponent layout={gridLayout} />
            {/if}
        </main>
        <aside class="dashboard-pane" style={getPaneStyle()}>
            {#if showPane && tab.paneWidgets.length > 0}
                <div class="pane-widgets">
                    {#each tab.paneWidgets as widget (widget.id)}
                        <WidgetRenderer {widget} />
                    {/each}
                </div>
            {:else if showPane}
                <div class="pane-empty">
                    <span class="empty-text">Drop widgets here</span>
                </div>
            {/if}
        </aside>
    {:else if tab.template === "pane-left"}
        <aside class="dashboard-pane" style={getPaneStyle()}>
            {#if showPane && tab.paneWidgets.length > 0}
                <div class="pane-widgets">
                    {#each tab.paneWidgets as widget (widget.id)}
                        <WidgetRenderer {widget} />
                    {/each}
                </div>
            {:else if showPane}
                <div class="pane-empty">
                    <span class="empty-text">Drop widgets here</span>
                </div>
            {/if}
        </aside>
        <main class="dashboard-content">
            {#if tab.layoutMode === "free"}
                <FreeLayoutComponent layout={freeLayout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={dockLayout} />
            {:else}
                <GridLayoutComponent layout={gridLayout} />
            {/if}
        </main>
    {:else if tab.template === "pane-right"}
        <main class="dashboard-content">
            {#if tab.layoutMode === "free"}
                <FreeLayoutComponent layout={freeLayout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={dockLayout} />
            {:else}
                <GridLayoutComponent layout={gridLayout} />
            {/if}
        </main>
        <aside class="dashboard-pane" style={getPaneStyle()}>
            {#if showPane && tab.paneWidgets.length > 0}
                <div class="pane-widgets">
                    {#each tab.paneWidgets as widget (widget.id)}
                        <WidgetRenderer {widget} />
                    {/each}
                </div>
            {:else if showPane}
                <div class="pane-empty">
                    <span class="empty-text">Drop widgets here</span>
                </div>
            {/if}
        </aside>
    {/if}
</div>

<style>
    .dashboard-tab-view {
        display: flex;
        flex: 1;
        height: 100%;
        overflow: hidden;
        background: var(--surface-2, #f8f9fa);
        position: relative; /* For absolute internal positioning */
    }

    /* Slideshow Styles */
    .slideshow-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.95);
        z-index: 9999;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        outline: none;
    }

    .slideshow-content {
        width: 100%;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        aspect-ratio: 16/9;
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1;
        flex-direction: column;
        /* No padding needed if we use absolute positioning for controls outside */
    }

    .slideshow-frame {
        width: 100%;
        height: 100%;
        position: relative;
    }

    .widget-wrapper {
        width: 100%;
        height: 100%;
    }

    .slideshow-frame :global(.widget) {
        width: 100%;
        height: 100%;
    }

    /* Override widget positioning styles for slideshow */
    .slideshow-frame :global(.widget.floating),
    .slideshow-frame :global(.widget.maximized) {
        position: relative !important;
        inset: auto !important;
        width: 100% !important;
        height: 100% !important;
        z-index: 0 !important;
    }

    /* Hide the widget titlebar/toolbar when in slideshow */
    .slideshow-frame :global(.widget-titlebar) {
        display: none !important;
    }

    .controls-container {
        position: absolute;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%);
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        z-index: 100;
        width: auto;
    }

    .end-message {
        font-size: 0.9rem;
        color: rgba(255, 255, 255, 0.6);
        font-weight: 500;
        letter-spacing: 0.5px;
    }

    .controls-bar {
        display: flex;
        align-items: center;
        gap: 16px;
        background: rgba(
            30,
            30,
            30,
            0.85
        ); /* Darker background as per screenshot style */
        padding: 8px 20px;
        border-radius: 50px;
        backdrop-filter: blur(10px);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        border: 1px solid rgba(255, 255, 255, 0.1);
    }

    .control-btn {
        background: transparent;
        border: none;
        color: white;
        font-size: 1.2rem;
        cursor: pointer;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        transition: background 0.2s;
    }

    .control-btn:hover {
        background: rgba(255, 255, 255, 0.1);
    }

    .control-btn.danger:hover {
        background: rgba(220, 53, 69, 0.3);
        color: #ffcccc;
    }

    .interval-input {
        display: flex;
        align-items: center;
        gap: 6px;
        color: rgba(255, 255, 255, 0.8);
        font-size: 0.9rem;
    }

    .interval-input input {
        width: 40px;
        background: rgba(255, 255, 255, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: white;
        padding: 2px 4px;
        border-radius: 4px;
        text-align: center;
        font-size: 0.9rem;
    }

    .separator {
        width: 1px;
        height: 18px;
        background: rgba(255, 255, 255, 0.2);
    }

    .progress-info {
        color: rgba(255, 255, 255, 0.9);
        font-feature-settings: "tnum";
        font-weight: 500;
        font-size: 0.95rem;
    }

    /* Vertical templates */
    .template-default,
    .template-pane-top,
    .template-pane-bottom {
        flex-direction: column;
    }

    /* Horizontal templates */
    .template-pane-left,
    .template-pane-right {
        flex-direction: row;
    }

    .dashboard-pane {
        background: var(--surface, #fff);
        border: 1px solid var(--border, #e8eaed);
        overflow: auto;
        flex-shrink: 0;
    }

    /* Pane borders based on position */
    .template-pane-top .dashboard-pane {
        border-top: none;
        border-left: none;
        border-right: none;
    }

    .template-pane-bottom .dashboard-pane {
        border-bottom: none;
        border-left: none;
        border-right: none;
    }

    .template-pane-left .dashboard-pane {
        border-top: none;
        border-bottom: none;
        border-left: none;
    }

    .template-pane-right .dashboard-pane {
        border-top: none;
        border-bottom: none;
        border-right: none;
    }

    .template-default .dashboard-pane {
        height: 0;
        border: none;
        overflow: hidden;
    }

    .pane-widgets {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 12px;
    }

    .pane-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--text-3, #9aa0a6);
        font-size: 0.85rem;
    }

    .dashboard-content {
        flex: 1;
        overflow: auto;
        display: flex;
    }

    /* Component Layout Mode */
    .component-mode {
        flex-direction: column;
    }

    .component-content {
        padding: 24px;
        background: var(--surface-2, #f8f9fa);
    }

    .component-missing {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        text-align: center;
        color: var(--text-2, #5f6368);
    }

    .missing-icon {
        font-size: 3rem;
        margin-bottom: 16px;
    }

    .component-missing p {
        margin: 0;
        font-size: 1rem;
    }
</style>
