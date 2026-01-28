<script lang="ts">
    import type { DashboardTab as DashboardTabClass } from "../../domain/dashboard-tab.svelte.js";
    import GridLayoutComponent from "../layouts/grid-layout.svelte";
    import FreeLayoutComponent from "../layouts/free-layout.svelte";
    import DockLayoutComponent from "../layouts/dock-layout.svelte";
    import WidgetRenderer from "../widgets/widget-renderer.svelte";
    import { getComponent } from "../../domain/component-registry.js";

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
</script>

<div
    class="dashboard-tab-view {templateClass}"
    class:component-mode={tab.layoutMode === "component"}
>
    {#if tab.layoutMode === "component"}
        <!-- Component Layout Mode: render full module component -->
        <main class="dashboard-content component-content">
            {#if ModuleComponent}
                <svelte:component this={ModuleComponent} />
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
                <FreeLayoutComponent layout={tab.layout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={tab.layout} />
            {:else}
                <GridLayoutComponent layout={tab.layout} />
            {/if}
        </main>
    {:else if tab.template === "pane-bottom"}
        <main class="dashboard-content">
            {#if tab.layoutMode === "free"}
                <FreeLayoutComponent layout={tab.layout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={tab.layout} />
            {:else}
                <GridLayoutComponent layout={tab.layout} />
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
                <FreeLayoutComponent layout={tab.layout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={tab.layout} />
            {:else}
                <GridLayoutComponent layout={tab.layout} />
            {/if}
        </main>
    {:else if tab.template === "pane-right"}
        <main class="dashboard-content">
            {#if tab.layoutMode === "free"}
                <FreeLayoutComponent layout={tab.layout} />
            {:else if tab.layoutMode === "dock"}
                <DockLayoutComponent layout={tab.layout} />
            {:else}
                <GridLayoutComponent layout={tab.layout} />
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
