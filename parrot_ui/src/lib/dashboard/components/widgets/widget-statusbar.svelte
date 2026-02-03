<script lang="ts">
    import type { Widget } from '../../domain/widget.svelte.js';

    interface Props {
        widget: Widget;
        onResizeStart?: (e: PointerEvent) => void;
    }

    let { widget, onResizeStart }: Props = $props();
</script>

<div class="widget-statusbar">
    <span class="status-message">{widget.statusMessage}</span>
    {#if widget.resizable}
        <div
            class="resize-handle"
            title="Resize"
            role="separator"
            tabindex="-1"
            onpointerdown={onResizeStart}
        ></div>
    {/if}
</div>

<style>
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
</style>
