<script lang="ts">
    import type { HtmlWidget } from "../../domain/html-widget.svelte.js";
    import {
        TextEditor,
        ToolbarRowWrapper,
        FormatButtonGroup,
        HeadingButtonGroup,
        ListButtonGroup,
        AlignmentButtonGroup,
        LayoutButtonGroup,
        SourceButtonGroup,
        UndoRedoButtonGroup,
        Divider,
    } from "@flowbite-svelte-plugins/texteditor";
    import type { Editor } from "@tiptap/core";

    interface Props {
        widget: HtmlWidget;
        onChange: (config: { content: string }) => void;
    }

    let { widget, onChange }: Props = $props();

    let editorInstance = $state<Editor | null>(null);

    // Initial content from widget
    const initialContent =
        widget.content || "<p>Enter HTML content here...</p>";

    // Update onChange when editor content changes
    $effect(() => {
        if (editorInstance) {
            const unsubscribe = editorInstance.on("update", () => {
                const html = editorInstance?.getHTML() ?? "";
                onChange({ content: html });
            });
            return () => {
                // Cleanup - no direct unsubscribe needed for tiptap
            };
        }
    });
</script>

<div class="html-editor-tab">
    <TextEditor
        bind:editor={editorInstance}
        content={initialContent}
        isEditable={true}
        contentprops={{ id: "html-widget-editor" }}
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
            <LayoutButtonGroup editor={editorInstance} />
            <Divider />
            <SourceButtonGroup editor={editorInstance} />
        </ToolbarRowWrapper>
    </TextEditor>
</div>

<style>
    .html-editor-tab {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 350px;
    }

    .html-editor-tab :global(.tiptap-container) {
        flex: 1;
        display: flex;
        flex-direction: column;
    }

    .html-editor-tab :global(.tiptap) {
        flex: 1;
        min-height: 250px;
        padding: 1rem;
        overflow-y: auto;
    }

    /* Fix toolbar layout for non-Tailwind projects */
    .html-editor-tab :global(.flex) {
        display: flex !important;
    }

    .html-editor-tab :global(.flex-wrap) {
        flex-wrap: wrap;
    }

    .html-editor-tab :global(.items-center) {
        align-items: center;
    }

    .html-editor-tab :global(.gap-1) {
        gap: 0.25rem;
    }

    .html-editor-tab :global(.gap-2) {
        gap: 0.5rem;
    }

    .html-editor-tab :global(.border-b) {
        border-bottom: 1px solid var(--border, #e5e7eb);
    }

    .html-editor-tab :global(.p-2) {
        padding: 0.5rem;
    }

    .html-editor-tab :global(.rounded-lg) {
        border-radius: 0.5rem;
    }

    .html-editor-tab :global(.bg-gray-100),
    .html-editor-tab :global(.dark\:bg-gray-700) {
        background-color: var(--surface, #f3f4f6);
    }

    .html-editor-tab :global(button.cursor-pointer) {
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
    .html-editor-tab :global(button.cursor-pointer span) {
        display: none;
    }

    /* Ensure icons are visible */
    .html-editor-tab :global(button.cursor-pointer svg) {
        display: block;
        width: 1.25rem;
        height: 1.25rem;
    }

    .html-editor-tab :global(button.cursor-pointer:hover) {
        background-color: var(--border, #e5e7eb);
    }

    .html-editor-tab :global(.divide-x > :not(:first-child)) {
        border-left: 1px solid var(--border, #e5e7eb);
        padding-left: 0.25rem;
        margin-left: 0.25rem;
    }
</style>
