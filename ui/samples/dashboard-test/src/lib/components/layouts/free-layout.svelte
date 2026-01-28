<!-- free-layout.svelte -->
<!-- Presentation layer - Absolute positioning with drag & resize -->

<script lang="ts">
    import type { FreeLayout } from "../../domain/layouts/free-layout.svelte.js";
    import WidgetRenderer from "../widgets/widget-renderer.svelte";

    interface Props {
        layout: FreeLayout;
    }

    let { layout }: Props = $props();

    // Local drag state for real-time animation
    // This tracks positions during drag before committing to domain
    let dragPositions = $state<Map<string, { x: number; y: number }>>(
        new Map(),
    );

    // === Drag Handlers ===

    function handleMouseDown(e: MouseEvent, widgetId: string) {
        if ((e.target as HTMLElement).classList.contains("resize-handle"))
            return;
        e.preventDefault();

        const position = layout.getPosition(widgetId);
        if (!position) return;

        // Initialize local drag position
        dragPositions.set(widgetId, { x: position.x, y: position.y });
        dragPositions = new Map(dragPositions); // Trigger reactivity

        layout.startDrag(widgetId, e.clientX, e.clientY);

        const onMove = (moveEvent: MouseEvent) => {
            // Update local position for immediate visual feedback
            const dx = moveEvent.clientX - layout.dragState.startX;
            const dy = moveEvent.clientY - layout.dragState.startY;

            let newX = layout.dragState.offsetX + dx;
            let newY = layout.dragState.offsetY + dy;

            // Apply constraints
            newX = Math.max(0, newX);
            newY = Math.max(0, newY);

            // Apply grid snapping if enabled
            if (layout.config.snapToGrid) {
                newX =
                    Math.round(newX / layout.config.gridSize) *
                    layout.config.gridSize;
                newY =
                    Math.round(newY / layout.config.gridSize) *
                    layout.config.gridSize;
            }

            dragPositions.set(widgetId, { x: newX, y: newY });
            dragPositions = new Map(dragPositions); // Trigger reactivity

            // Also update domain for final commit
            layout.updateDrag(moveEvent.clientX, moveEvent.clientY);
        };

        const onUp = () => {
            // Clear local drag position
            dragPositions.delete(widgetId);
            dragPositions = new Map(dragPositions);

            layout.endDrag();
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    }

    // === Resize Handlers ===

    type ResizeHandle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

    function handleResizeStart(
        e: MouseEvent,
        widgetId: string,
        handle: ResizeHandle,
    ) {
        e.preventDefault();
        e.stopPropagation();
        layout.startResize(widgetId, handle, e.clientX, e.clientY);

        const onMove = (moveEvent: MouseEvent) => {
            layout.updateResize(moveEvent.clientX, moveEvent.clientY);
        };

        const onUp = () => {
            layout.endResize();
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    }

    // Keyboard handling for accessibility
    function handleKeyDown(e: KeyboardEvent, widgetId: string) {
        if (e.key === "Escape" && layout.dragState.active) {
            dragPositions.delete(widgetId);
            dragPositions = new Map(dragPositions);
            layout.cancelDrag();
        }
    }

    // Helper to get current display position (drag position or stored position)
    function getDisplayPosition(widgetId: string) {
        const dragPos = dragPositions.get(widgetId);
        const storedPos = layout.getPosition(widgetId);
        if (!storedPos) return null;

        return {
            x: dragPos?.x ?? storedPos.x,
            y: dragPos?.y ?? storedPos.y,
            width: storedPos.width,
            height: storedPos.height,
            zIndex: storedPos.zIndex,
        };
    }
</script>

<div class="free-layout">
    {#each layout.getWidgets() as widget (widget.id)}
        {@const position = getDisplayPosition(widget.id)}
        {#if position}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
                class="free-widget"
                class:dragging={layout.dragState.widgetId === widget.id}
                class:resizing={layout.resizeState?.widgetId === widget.id}
                style="
                    left: {position.x}px;
                    top: {position.y}px;
                    width: {position.width}px;
                    height: {position.height}px;
                    z-index: {position.zIndex};
                "
                onmousedown={(e) => handleMouseDown(e, widget.id)}
                onkeydown={(e) => handleKeyDown(e, widget.id)}
            >
                <WidgetRenderer {widget} {layout} />

                <!-- Resize handles -->
                <div
                    class="resize-handle resize-n"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "n")}
                ></div>
                <div
                    class="resize-handle resize-s"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "s")}
                ></div>
                <div
                    class="resize-handle resize-e"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "e")}
                ></div>
                <div
                    class="resize-handle resize-w"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "w")}
                ></div>
                <div
                    class="resize-handle resize-ne"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "ne")}
                ></div>
                <div
                    class="resize-handle resize-nw"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "nw")}
                ></div>
                <div
                    class="resize-handle resize-se"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "se")}
                ></div>
                <div
                    class="resize-handle resize-sw"
                    onmousedown={(e) => handleResizeStart(e, widget.id, "sw")}
                ></div>
            </div>
        {/if}
    {/each}

    {#if layout.getWidgets().length === 0}
        <div class="free-empty">
            <span>No widgets. Add some from the menu.</span>
        </div>
    {/if}
</div>

<style>
    .free-layout {
        position: relative;
        width: 100%;
        height: 100%;
        overflow: auto;
        background: linear-gradient(
                90deg,
                rgba(0, 0, 0, 0.03) 1px,
                transparent 1px
            ),
            linear-gradient(rgba(0, 0, 0, 0.03) 1px, transparent 1px);
        background-size: 20px 20px;
    }

    .free-widget {
        position: absolute;
        display: flex;
        flex-direction: column;
        background: var(--surface, #fff);
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        overflow: hidden;
        transition: box-shadow 0.15s;
    }

    .free-widget:hover {
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
    }

    .free-widget.dragging {
        opacity: 0.9;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        cursor: grabbing;
    }

    .free-widget.resizing {
        outline: 2px solid var(--primary, #3b82f6);
    }

    /* Resize Handles */
    .resize-handle {
        position: absolute;
        background: transparent;
    }

    .resize-n,
    .resize-s {
        left: 8px;
        right: 8px;
        height: 6px;
        cursor: ns-resize;
    }

    .resize-n {
        top: 0;
    }
    .resize-s {
        bottom: 0;
    }

    .resize-e,
    .resize-w {
        top: 8px;
        bottom: 8px;
        width: 6px;
        cursor: ew-resize;
    }

    .resize-e {
        right: 0;
    }
    .resize-w {
        left: 0;
    }

    .resize-ne,
    .resize-nw,
    .resize-se,
    .resize-sw {
        width: 12px;
        height: 12px;
    }

    .resize-ne {
        top: 0;
        right: 0;
        cursor: nesw-resize;
    }
    .resize-nw {
        top: 0;
        left: 0;
        cursor: nwse-resize;
    }
    .resize-se {
        bottom: 0;
        right: 0;
        cursor: nwse-resize;
    }
    .resize-sw {
        bottom: 0;
        left: 0;
        cursor: nesw-resize;
    }

    .resize-handle:hover {
        background: rgba(59, 130, 246, 0.2);
    }

    .free-empty {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted, #9ca3af);
        font-size: 14px;
    }
</style>
