<!-- dock-layout.svelte -->
<!-- Presentation layer - Projects domain state -->

<script lang="ts">
    import type {
        DockLayout,
        PaneStructure,
    } from "../../domain/layouts/dock-layout.svelte.js";
    import WidgetRenderer from "../widgets/widget-renderer.svelte";

    interface Props {
        layout: DockLayout;
    }

    let { layout }: Props = $props();

    // Pane menu state
    let openPaneMenu = $state<string | null>(null);

    // === Event Handlers (delegate to domain) ===

    function handleTabClick(paneId: string, widgetId: string) {
        layout.activateWidgetInPane(paneId, widgetId);
    }

    function handleTabDragStart(
        e: DragEvent,
        widgetId: string,
        paneId: string,
    ) {
        e.dataTransfer?.setData("text/plain", widgetId);
        e.dataTransfer!.effectAllowed = "move";
        layout.startWidgetDrag(widgetId, paneId);
    }

    function handlePaneDragOver(e: DragEvent, paneId: string) {
        if (!layout.dragState.active) return;
        e.preventDefault();
        layout.updateDragTarget(paneId);
    }

    function handlePaneDragLeave(paneId: string) {
        if (layout.dragState.targetPane === paneId) {
            layout.updateDragTarget(null);
        }
    }

    function handlePaneDrop(e: DragEvent) {
        e.preventDefault();
        layout.endWidgetDrag();
    }

    function handleDragEnd() {
        layout.cancelWidgetDrag();
    }

    // Pane menu handlers
    function togglePaneMenu(paneId: string) {
        openPaneMenu = openPaneMenu === paneId ? null : paneId;
    }

    function closePaneMenu() {
        openPaneMenu = null;
    }

    function handleSplitHorizontal(paneId: string) {
        layout.splitPane(paneId, "horizontal");
        closePaneMenu();
    }

    function handleSplitVertical(paneId: string) {
        layout.splitPane(paneId, "vertical");
        closePaneMenu();
    }

    function handleClosePane(paneId: string) {
        layout.closePane(paneId);
        closePaneMenu();
    }

    // Gutter resize
    function handleGutterPointerDown(
        e: PointerEvent,
        containerId: string,
        gutterIndex: number,
        isHorizontal: boolean,
    ) {
        e.preventDefault();
        (e.target as HTMLElement).setPointerCapture(e.pointerId);

        const startPos = isHorizontal ? e.clientX : e.clientY;
        layout.startGutterResize(containerId, gutterIndex, startPos);

        const container = (e.target as HTMLElement).parentElement!;

        const onMove = (moveEvent: PointerEvent) => {
            const currentPos = isHorizontal
                ? moveEvent.clientX
                : moveEvent.clientY;
            const containerSize = isHorizontal
                ? container.offsetWidth
                : container.offsetHeight;
            layout.updateGutterResize(currentPos, containerSize);
        };

        const onUp = (upEvent: PointerEvent) => {
            (upEvent.target as HTMLElement).releasePointerCapture(
                upEvent.pointerId,
            );
            layout.endGutterResize();
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }
</script>

<svelte:window onclick={closePaneMenu} />

<!-- Recursive structure renderer -->
{#snippet renderStructure(
    structure: PaneStructure,
    containerId: string,
    depth: number,
)}
    {#if structure.type === "pane"}
        {@const paneId = structure.id ?? containerId}
        {@const pane = layout.getPane(paneId)}
        {@const paneWidgets = layout.getPaneWidgets(paneId)}
        {@const activeWidget = layout.getActiveWidgetForPane(paneId)}
        {@const isDropTarget = layout.dragState.targetPane === paneId}

        <div
            class="dock-pane"
            class:drop-target={isDropTarget}
            data-pane-id={paneId}
            role="region"
            aria-label="Dock pane"
            ondragover={(e) => handlePaneDragOver(e, paneId)}
            ondragleave={() => handlePaneDragLeave(paneId)}
            ondrop={handlePaneDrop}
        >
            <!-- Tab bar -->
            <div class="dock-pane-tabs" role="tablist">
                {#each paneWidgets as widget (widget.id)}
                    {@const isActive = pane?.activeWidgetId === widget.id}
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div
                        class="dock-tab"
                        class:active={isActive}
                        draggable="true"
                        role="tab"
                        tabindex="0"
                        aria-selected={isActive}
                        onclick={() => handleTabClick(paneId, widget.id)}
                        onkeydown={(e) =>
                            e.key === "Enter" &&
                            handleTabClick(paneId, widget.id)}
                        onpointerdown={(e) => {
                            if (
                                (e.target as HTMLElement).closest(
                                    ".dock-tab-close",
                                )
                            )
                                return;
                            handleTabClick(paneId, widget.id);
                        }}
                        ondragstart={(e) =>
                            handleTabDragStart(e, widget.id, paneId)}
                        ondragend={handleDragEnd}
                    >
                        <span class="dock-tab-icon">{widget.icon}</span>
                        <span class="dock-tab-title">{widget.title}</span>
                        <button
                            class="dock-tab-close"
                            onclick={(e) => {
                                e.stopPropagation();
                                widget.close();
                            }}
                            aria-label="Close tab"
                        >
                            ×
                        </button>
                    </div>
                {/each}

                <!-- Pane menu button -->
                <div class="dock-pane-toolbar">
                    <button
                        class="dock-pane-menu-btn"
                        title="Pane options"
                        onclick={(e) => {
                            e.stopPropagation();
                            togglePaneMenu(paneId);
                        }}>▾</button
                    >

                    {#if openPaneMenu === paneId}
                        <!-- svelte-ignore a11y_no_static_element_interactions -->
                        <div
                            class="pane-menu-dropdown"
                            onclick={(e) => e.stopPropagation()}
                        >
                            <button
                                onclick={() => handleSplitHorizontal(paneId)}
                            >
                                ↔ Split Horizontal
                            </button>
                            <button onclick={() => handleSplitVertical(paneId)}>
                                ↕ Split Vertical
                            </button>
                            <hr />
                            <button onclick={() => handleClosePane(paneId)}>
                                ✕ Close Pane
                            </button>
                        </div>
                    {/if}
                </div>
            </div>

            <!-- Content area -->
            <div
                class="dock-pane-content"
                role="tabpanel"
                onpointerdown={() =>
                    activeWidget &&
                    layout.activateWidgetInPane(paneId, activeWidget.id)}
            >
                {#if activeWidget}
                    <WidgetRenderer widget={activeWidget} {layout} />
                {:else}
                    <div class="dock-pane-empty">
                        {#if layout.dragState.active}
                            <span>Drop widget here</span>
                        {:else}
                            <span>Empty pane</span>
                        {/if}
                    </div>
                {/if}

                <!-- Drop zone indicator -->
                {#if isDropTarget}
                    <div class="dock-pane-dropzone">
                        <span>Drop to add</span>
                    </div>
                {/if}
            </div>
        </div>
    {:else}
        <!-- Row or Column container -->
        {@const isRow = structure.type === "row"}
        {@const containerKey = structure.id ?? containerId}
        {@const sizes =
            layout.paneSizes.get(containerKey) ?? structure.sizes ?? []}

        <div
            class="dock-container"
            class:dock-row={isRow}
            class:dock-column={!isRow}
            data-container-id={containerKey}
        >
            {#each structure.children ?? [] as child, index (index)}
                <!-- Child element with flex size -->
                <div
                    class="dock-child"
                    style="flex: {sizes[index] ?? 1} {sizes[index] ?? 1} 0px"
                >
                    {@render renderStructure(
                        child,
                        child.id ?? `${containerKey}-${index}`,
                        depth + 1,
                    )}
                </div>

                <!-- Gutter between children (except after last) -->
                {#if index < (structure.children?.length ?? 0) - 1}
                    <div
                        class="dock-gutter"
                        class:horizontal={isRow}
                        class:vertical={!isRow}
                        role="separator"
                        aria-orientation={isRow ? "vertical" : "horizontal"}
                        onpointerdown={(e) =>
                            handleGutterPointerDown(
                                e,
                                containerKey,
                                index,
                                isRow,
                            )}
                    ></div>
                {/if}
            {/each}
        </div>
    {/if}
{/snippet}

<!-- Main layout container -->
<div class="dock-layout">
    {#if layout.currentTemplate}
        {@render renderStructure(layout.currentTemplate.structure, "root", 0)}
    {:else}
        <div class="dock-empty">No template applied</div>
    {/if}
</div>

<style>
    .dock-layout {
        height: 100%;
        width: 100%;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        flex: 1;
        min-height: 0;
        min-width: 0;
    }

    /* === Containers === */
    .dock-container {
        display: flex;
        flex: 1;
        min-width: 0;
        min-height: 0;
        width: 100%;
        height: 100%;
    }

    .dock-row {
        flex-direction: row;
    }

    .dock-column {
        flex-direction: column;
    }

    .dock-child {
        min-width: 0;
        min-height: 0;
        overflow: hidden;
        display: flex;
    }

    /* === Gutters === */
    .dock-gutter {
        flex-shrink: 0;
        background: var(--gutter-bg, #e5e7eb);
        transition: background 0.15s;
    }

    .dock-gutter:hover {
        background: var(--gutter-hover, #3b82f6);
    }

    .dock-gutter.horizontal {
        width: 6px;
        cursor: col-resize;
    }

    .dock-gutter.vertical {
        height: 6px;
        cursor: row-resize;
    }

    /* === Panes === */
    .dock-pane {
        display: flex;
        flex-direction: column;
        height: 100%;
        width: 100%;
        flex: 1;
        min-width: 0;
        min-height: 0;
        background: var(--pane-bg, #f8f9fa);
        border-radius: 8px;
        border: 1px solid var(--border, #e5e7eb);
        overflow: hidden;
        position: relative;
    }

    .dock-pane.drop-target {
        border-color: var(--accent, #3b82f6);
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
    }

    /* === Tab Bar === */
    .dock-pane-tabs {
        display: flex;
        align-items: center;
        gap: 2px;
        padding: 4px 8px;
        background: var(--pane-header, #e9ecef);
        border-bottom: 1px solid var(--border, #e5e7eb);
        min-height: 36px;
        flex-wrap: wrap;
    }

    .dock-pane-toolbar {
        margin-left: auto;
    }

    .dock-pane-menu-btn {
        background: transparent;
        border: none;
        color: var(--text-muted, #6b7280);
        cursor: pointer;
        padding: 4px 8px;
        font-size: 12px;
    }

    .dock-pane-toolbar {
        position: relative;
    }

    .pane-menu-dropdown {
        position: absolute;
        top: 100%;
        right: 0;
        z-index: 100;
        min-width: 160px;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #e5e7eb);
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        padding: 4px;
    }

    .pane-menu-dropdown button {
        display: block;
        width: 100%;
        text-align: left;
        padding: 8px 12px;
        background: none;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 13px;
        color: var(--text, #111827);
    }

    .pane-menu-dropdown button:hover {
        background: var(--surface-hover, #f3f4f6);
    }

    .pane-menu-dropdown hr {
        margin: 4px 0;
        border: none;
        border-top: 1px solid var(--border, #e5e7eb);
    }

    /* === Tabs === */
    .dock-tab {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 12px;
        background: transparent;
        border: none;
        border-radius: 4px 4px 0 0;
        color: var(--text-muted, #6b7280);
        cursor: pointer;
        font-size: 12px;
        transition: all 0.15s;
    }

    .dock-tab:hover {
        background: var(--surface-hover, rgba(0, 0, 0, 0.05));
    }

    .dock-tab.active {
        background: var(--surface, #fff);
        color: var(--text, #111827);
        font-weight: 600;
    }

    .dock-tab-icon {
        font-size: 14px;
    }

    .dock-tab-close {
        margin-left: 4px;
        padding: 0 4px;
        background: none;
        border: none;
        color: inherit;
        opacity: 0.5;
        cursor: pointer;
        font-size: 14px;
    }

    .dock-tab-close:hover {
        opacity: 1;
        color: var(--danger, #ef4444);
    }

    /* === Content === */
    .dock-pane-content {
        flex: 1;
        position: relative;
        overflow: hidden;
        min-height: 0;
    }

    .dock-pane-content > :global(.widget) {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
    }

    .dock-pane-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--text-muted, #9ca3af);
        font-size: 14px;
    }

    .dock-pane-dropzone {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(59, 130, 246, 0.1);
        border: 2px dashed var(--accent, #3b82f6);
        border-radius: 4px;
        color: var(--accent, #3b82f6);
        font-weight: 600;
        pointer-events: none;
    }

    .dock-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--text-muted, #9ca3af);
    }
</style>
