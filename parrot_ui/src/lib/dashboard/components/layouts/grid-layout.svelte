<script lang="ts">
    import type { GridLayout } from "../../domain/layouts/grid-layout.svelte.js";
    import WidgetRenderer from "../widgets/widget-renderer.svelte";

    interface Props {
        layout: GridLayout;
    }

    let { layout }: Props = $props();

    // Reference to the grid element for calculating positions
    let gridEl: HTMLDivElement | null = null;

    // CSS Grid style derived from config
    // We use minmax for rows to ensure they have a minimum viable height, allowing the grid to grow
    let gridStyle = $derived(`
        display: grid;
        grid-template-columns: repeat(${layout.config.cols}, 1fr);
        grid-template-rows: repeat(${layout.config.rows}, minmax(80px, 1fr));
        gap: ${layout.config.gap}px;
        padding: ${layout.config.gap}px;
        min-height: 100%;
        width: 100%;
    `);

    // Helper to calculate cell from point
    function cellFromPoint(
        clientX: number,
        clientY: number,
    ): { row: number; col: number } | null {
        if (!gridEl) return null;
        const rect = gridEl.getBoundingClientRect();

        const { cols, rows, gap } = layout.config;
        const contentWidth = rect.width - gap * 2;
        const contentHeight = rect.height - gap * 2;
        const cellWidth = contentWidth / cols;
        const cellHeight = contentHeight / rows;

        const x = clientX - rect.left - gap;
        const y = clientY - rect.top - gap;

        // Clamp columns (fixed width)
        const col = Math.max(0, Math.min(cols - 1, Math.floor(x / cellWidth)));

        // Don't clamp rows strictly to allow expansion interaction
        // We still clamp to 0 minimum
        const row = Math.max(0, Math.floor(y / cellHeight));

        return { row, col };
    }

    // Pointer-based drag handlers (more reliable than HTML5 drag)
    function handlePointerDown(e: PointerEvent, widgetId: string) {
        // Ignore if clicking on widget controls
        const target = e.target as HTMLElement;
        if (target.closest(".widget-toolbar") || target.closest("button"))
            return;

        // Ignore if widget is floating (handled by widget itself)
        const widget = layout.getWidgets().find((w) => w.id === widgetId);
        if (widget?.isFloating) return;

        e.preventDefault();
        layout.startDrag(widgetId);

        const onMove = (moveEvent: PointerEvent) => {
            const cell = cellFromPoint(moveEvent.clientX, moveEvent.clientY);
            if (!cell) return;

            const currentPlacement = layout.getPlacement(widgetId);
            if (currentPlacement) {
                layout.updateDragPreview({
                    row: cell.row,
                    col: cell.col,
                    rowSpan: currentPlacement.rowSpan,
                    colSpan: currentPlacement.colSpan,
                });
            }
        };

        const onUp = () => {
            layout.endDrag();
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    function handleResizeStart(e: PointerEvent, widgetId: string) {
        console.log("[GridLayout] handleResizeStart", { widgetId });
        // Prevent default drag
        e.stopPropagation();
        e.preventDefault();

        // 1. Tell layout to start resize
        // We pass 'se' (southeast) as handle for now since that's the only one we expose
        layout.startResize(widgetId, "se", e.clientX, e.clientY);

        const onMove = (moveEvent: PointerEvent) => {
            const cell = cellFromPoint(moveEvent.clientX, moveEvent.clientY);
            // console.log('[GridLayout] onMove', { cell });
            layout.updateResize(
                moveEvent.clientX,
                moveEvent.clientY,
                () => cell,
            );
        };

        const onUp = (upEvent: PointerEvent) => {
            console.log("[GridLayout] endResize");
            layout.endResize();
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    function handleKeyDown(e: KeyboardEvent) {
        if (e.key === "Escape" && layout.dragState.active) {
            layout.cancelDrag();
        }
    }
</script>

<svelte:window onkeydown={handleKeyDown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="grid-layout" style={gridStyle} bind:this={gridEl} role="grid">
    <!-- Widgets -->
    {#each layout.getWidgets() as widget (widget.id)}
        {@const placement = layout.getPlacement(widget.id)}
        {#if placement}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
                class="grid-cell"
                class:dragging={layout.dragState.widgetId === widget.id}
                class:swap-target={layout.dragState.swapTarget === widget.id}
                style="
                    grid-column: {placement.col + 1} / span {placement.colSpan};
                    grid-row: {placement.row + 1} / span {placement.rowSpan};
                "
                onpointerdown={(e) => handlePointerDown(e, widget.id)}
            >
                <WidgetRenderer
                    {widget}
                    onResizeStart={(e) => handleResizeStart(e, widget.id)}
                />
            </div>
        {/if}
    {/each}

    <!-- Drop preview -->
    {#if layout.dragState.active && layout.dragState.preview && layout.dragState.widgetId}
        {@const preview = layout.dragState.preview}
        {@const isSwap = layout.dragState.swapTarget !== null}
        <div
            class="drop-preview"
            class:swap-mode={isSwap}
            style:grid-column="{preview.col + 1} / span {preview.colSpan}"
            style:grid-row="{preview.row + 1} / span {preview.rowSpan}"
        >
            <div class="drop-indicator">
                {#if isSwap}
                    <span class="swap-label">⇄ Swap</span>
                {/if}
            </div>
        </div>
    {/if}
</div>

<style>
    .grid-layout {
        position: relative;
        box-sizing: border-box;
    }

    .grid-cell {
        min-width: 0;
        min-height: 0;
        transition:
            transform 0.1s,
            opacity 0.15s;
        cursor: grab;
    }

    .grid-cell:active {
        cursor: grabbing;
    }

    .grid-cell.dragging {
        opacity: 0.5;
        filter: grayscale(1);
        pointer-events: none;
    }

    .grid-cell.swap-target {
        outline: 3px solid #22c55e;
        outline-offset: -3px;
        border-radius: 8px;
    }

    .drop-preview {
        border-radius: 8px;
        z-index: 0;
        pointer-events: none;
        position: relative;
    }

    .drop-indicator {
        position: absolute;
        inset: 4px;
        background: rgba(59, 130, 246, 0.1);
        border: 2px dashed #3b82f6;
        border-radius: 6px;
        animation: pulse 1.5s infinite;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .drop-preview.swap-mode .drop-indicator {
        background: rgba(34, 197, 94, 0.15);
        border-color: #22c55e;
    }

    .swap-label {
        color: #22c55e;
        font-weight: 600;
        font-size: 0.875rem;
        background: rgba(255, 255, 255, 0.9);
        padding: 4px 12px;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    @keyframes pulse {
        0% {
            opacity: 0.5;
        }
        50% {
            opacity: 1;
        }
        100% {
            opacity: 0.5;
        }
    }
</style>
