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
            tabindex="0"
            bind:this={slideshowOverlay}
            onkeydown={handleKeydown}
        >
            <!-- Content Container -->
            <div class="slideshow-content" transition:fade={{ duration: 300 }}>
                <div class="slideshow-frame">
                    <WidgetRenderer widget={slideshowWidget} />
                </div>
            </div>

            <!-- Controls -->
            <button
                class="nav-btn prev"
                onclick={() => tab.slideshowPrev()}
                title="Previous (Left Arrow)"
            >
                ‹
            </button>
            <button
                class="nav-btn next"
                onclick={() => tab.slideshowNext()}
                title="Next (Right Arrow)"
            >
                ›
            </button>
            <button
                class="close-btn"
                onclick={handleClose}
                title="Exit Slideshow (Esc)"
            >
                ×
            </button>

            <!-- Progress -->
            <div class="slideshow-progress">
                {tab.slideshowState.index + 1} / {tab.slideshowState.widgets
                    .length}
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
        background: rgba(0, 0, 0, 0.9);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        outline: none;
    }

    .slideshow-content {
        width: 90%;
        height: 85%;
        max-width: 1400px;
        position: relative;
        display: flex;
        align-items: stretch;
        justify-content: stretch;
        z-index: 1;
    }

    .slideshow-frame {
        width: 100%;
        height: 100%;
    }

    .slideshow-frame :global(.widget) {
        width: 100%;
        height: 100%;
    }

    .slideshow-frame :global(.widget.floating),
    .slideshow-frame :global(.widget.maximized) {
        position: relative !important;
        inset: auto !important;
        width: 100% !important;
        height: 100% !important;
        z-index: 0 !important;
    }

    .nav-btn {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
        background: rgba(255, 255, 255, 0.1);
        color: white;
        border: none;
        width: 60px;
        height: 60px;
        border-radius: 50%;
        font-size: 2rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
        z-index: 2;
    }

    .nav-btn:hover {
        background: rgba(255, 255, 255, 0.2);
    }

    .nav-btn.prev {
        left: 40px;
    }
    .nav-btn.next {
        right: 40px;
    }

    .close-btn {
        position: absolute;
        top: 40px;
        right: 40px;
        background: transparent;
        color: white;
        border: none;
        font-size: 2.5rem;
        cursor: pointer;
        opacity: 0.7;
        transition: opacity 0.2s;
        z-index: 2;
    }

    .close-btn:hover {
        opacity: 1;
    }

    .slideshow-progress {
        position: absolute;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%);
        color: rgba(255, 255, 255, 0.6);
        font-feature-settings: "tnum";
        z-index: 2;
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
