<script lang="ts">
    import type { MarkdownWidget } from "../../domain/markdown-widget.svelte.js";
    import {
        TextEditor,
        ToolbarRowWrapper,
        FormatButtonGroup,
        HeadingButtonGroup,
        ListButtonGroup,
        AlignmentButtonGroup,
        SourceButtonGroup,
        UndoRedoButtonGroup,
        Divider,
    } from "@flowbite-svelte-plugins/texteditor";
    import type { Editor } from "@tiptap/core";
    import TurndownService from "turndown";

    interface Props {
        widget: MarkdownWidget;
        onChange: (config: { content: string }) => void;
    }

    let { widget, onChange }: Props = $props();

    let editorInstance = $state<Editor | null>(null);

    // Convert markdown to HTML for editing, and back to markdown on save
    // For simplicity, we edit as HTML and export as markdown
    const turndown = new TurndownService();

    // Convert initial markdown to HTML for the editor
    import { marked } from "marked";
    const initialHtml = widget.content
        ? (marked.parse(widget.content) as string)
        : "<p>Enter markdown content here...</p>";

    // Update onChange when editor content changes - convert back to markdown
    $effect(() => {
        if (editorInstance) {
            editorInstance.on("update", () => {
                const html = editorInstance?.getHTML() ?? "";
                // Convert HTML back to markdown
                const markdown = turndown.turndown(html);
                onChange({ content: markdown });
            });
        }
    });
</script>

<div class="markdown-editor-tab">
    <div class="editor-header">
        <span class="header-title">📝 Markdown Editor</span>
        <span class="header-hint">Edit visually - saves as Markdown</span>
    </div>

    <TextEditor
        bind:editor={editorInstance}
        content={initialHtml}
        isEditable={true}
        contentprops={{ id: "markdown-widget-editor" }}
    >
        <ToolbarRowWrapper>
            <FormatButtonGroup editor={editorInstance} />
            <Divider />
            <HeadingButtonGroup editor={editorInstance} />
            <Divider />
            <ListButtonGroup editor={editorInstance} />
        </ToolbarRowWrapper>
        <ToolbarRowWrapper toolbarrawprops={{ top: false }}>
            <UndoRedoButtonGroup editor={editorInstance} />
            <Divider />
            <AlignmentButtonGroup editor={editorInstance} />
            <Divider />
            <SourceButtonGroup editor={editorInstance} />
        </ToolbarRowWrapper>
    </TextEditor>
</div>

<style>
    .markdown-editor-tab {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 350px;
    }

    .editor-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.5rem;
        background: var(--surface, #f5f5f5);
        border: 1px solid var(--border, #ddd);
        border-radius: 4px 4px 0 0;
        border-bottom: none;
    }

    .header-title {
        font-weight: 500;
        color: var(--text, #333);
    }

    .header-hint {
        font-size: 0.8rem;
        color: var(--text-secondary, #666);
    }

    .markdown-editor-tab :global(.tiptap-container) {
        flex: 1;
        display: flex;
        flex-direction: column;
    }

    .markdown-editor-tab :global(.tiptap) {
        flex: 1;
        min-height: 250px;
        padding: 1rem;
        overflow-y: auto;
    }

    /* Fix toolbar layout for non-Tailwind projects */
    .markdown-editor-tab :global(.flex) {
        display: flex !important;
    }

    .markdown-editor-tab :global(.flex-wrap) {
        flex-wrap: wrap;
    }

    .markdown-editor-tab :global(.items-center) {
        align-items: center;
    }

    .markdown-editor-tab :global(.gap-1) {
        gap: 0.25rem;
    }

    .markdown-editor-tab :global(.gap-2) {
        gap: 0.5rem;
    }

    .markdown-editor-tab :global(.border-b) {
        border-bottom: 1px solid var(--border, #e5e7eb);
    }

    .markdown-editor-tab :global(.p-2) {
        padding: 0.5rem;
    }

    .markdown-editor-tab :global(.rounded-lg) {
        border-radius: 0.5rem;
    }

    .markdown-editor-tab :global(.bg-gray-100),
    .markdown-editor-tab :global(.dark\:bg-gray-700) {
        background-color: var(--surface, #f3f4f6);
    }

    .markdown-editor-tab :global(button.cursor-pointer) {
        cursor: pointer;
        padding: 0.375rem;
        border-radius: 0.25rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 32px;
        height: 32px;
    }

    /* Hide text labels in toolbar buttons */
    .markdown-editor-tab :global(button.cursor-pointer span) {
        display: none;
    }

    /* Ensure icons are visible */
    .markdown-editor-tab :global(button.cursor-pointer svg) {
        display: block;
        width: 1.25rem;
        height: 1.25rem;
    }

    .markdown-editor-tab :global(button.cursor-pointer:hover) {
        background-color: var(--border, #e5e7eb);
    }

    .markdown-editor-tab :global(.divide-x > :not(:first-child)) {
        border-left: 1px solid var(--border, #e5e7eb);
        padding-left: 0.25rem;
        margin-left: 0.25rem;
    }
</style>
