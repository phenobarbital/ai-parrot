<script lang="ts">
    import type { MarkdownWidget } from "../../domain/markdown-widget.svelte.js";

    interface Props {
        widget: MarkdownWidget;
        onChange: (config: { content: string }) => void;
    }

    let { widget, onChange }: Props = $props();
    let content = $state(widget.content ?? "");

    $effect(() => {
        onChange({ content });
    });
</script>

<div class="tab-section">
    <div class="form-group">
        <label for="markdown-content">Markdown Content</label>
        <textarea
            id="markdown-content"
            rows="10"
            bind:value={content}
        ></textarea>
    </div>
</div>

<style>
    .tab-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .form-group label {
        display: block;
        margin-bottom: 6px;
        font-size: 0.875rem;
        font-weight: 500;
    }

    textarea {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
        font-family: monospace;
    }
</style>
