<script lang="ts">
    import type { Widget } from "../models/widget.svelte.js";

    let { widget }: { widget: Widget } = $props();
</script>

<article
    class="widget"
    class:minimized={widget.minimized}
    class:maximized={widget.maximized}
    style:left="{widget.x}px"
    style:top="{widget.y}px"
    style:width="{widget.w}px"
    style:height={widget.minimized ? "auto" : widget.h + "px"}
>
    <header class="widget-header" ondblclick={() => widget.toggleMaximize()}>
        <div class="widget-title">
            <span class="icon">{widget.icon}</span>
            <span>{widget.title}</span>
        </div>

        <div class="widget-controls">
            <button
                type="button"
                onclick={() => widget.toggleMinimize()}
                title={widget.minimized ? "Restore" : "Minimize"}
            >
                {widget.minimized ? "+" : "−"}
            </button>
            <button
                type="button"
                onclick={() => widget.toggleMaximize()}
                title={widget.maximized ? "Restore" : "Maximize"}
            >
                {widget.maximized ? "❐" : "□"}
            </button>
        </div>
    </header>

    {#if !widget.minimized}
        <div class="widget-body">
            {#if widget.content}
                {@render widget.content()}
            {:else}
                <div class="empty-state">No content</div>
            {/if}
        </div>

        <!-- Todo: Resize handles -->
    {/if}
</article>

<style>
    .widget {
        position: absolute;
        display: flex;
        flex-direction: column;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #ccc);
        border-radius: 6px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        overflow: hidden;
        transition:
            width 0.2s,
            height 0.2s,
            box-shadow 0.2s;
    }

    .widget.maximized {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        z-index: 1000;
    }

    .widget-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        background: var(--surface-2, #f8f9fa);
        border-bottom: 1px solid var(--border-subtle, #eee);
        cursor: grab;
        user-select: none;
    }

    .widget-header:active {
        cursor: grabbing;
    }

    .widget-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 600;
        font-size: 0.9rem;
    }

    .widget-controls {
        display: flex;
        gap: 4px;
    }

    .widget-controls button {
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        color: var(--text-2, #666);
        line-height: 1;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .widget-controls button:hover {
        background: rgba(0, 0, 0, 0.05);
        color: var(--text, #000);
    }

    .widget-body {
        flex: 1;
        overflow: auto;
        padding: 12px;
        position: relative;
    }

    .empty-state {
        color: var(--text-2, #999);
        font-style: italic;
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
</style>
