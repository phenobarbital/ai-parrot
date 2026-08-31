<script lang="ts">
    /**
     * AppTextEditorLite — Compact TipTap rich-text editor.
     * Stripped-down version of AppTextEditor for single-purpose text fields
     * (e.g. agent goal, backstory). Single toolbar row, no source mode.
     *
     * Props match AppTextEditor for easy swap:
     *   content    — initial HTML string
     *   editable   — whether the editor is interactive (default: true)
     *   onchange   — callback receiving updated HTML on every change
     *   minHeight  — minimum editor height in px (default: 120)
     *   class      — extra CSS classes on the root element
     */
    // ai-parrot (FEAT-476 TASK-2593): @tiptap/* loaded only behind
    // features.richEditor — see AppTextEditor.svelte for the same pattern.
    import { onMount, onDestroy } from 'svelte';
    import Icon from '@iconify/svelte';
    import { features } from '$lib/features';
    import type { Editor as TiptapEditor } from '@tiptap/core';

    interface Props {
        content?: string;
        editable?: boolean;
        onchange?: (html: string) => void;
        minHeight?: number;
        class?: string;
    }

    let {
        content = '',
        editable = true,
        onchange,
        minHeight = 120,
        class: className = ''
    }: Props = $props();

    let editorElement: HTMLDivElement | undefined = $state();
    let editor: TiptapEditor | undefined = $state();
    let plainContent = $state(content);

    // Toolbar reactive state
    let isBold = $state(false);
    let isItalic = $state(false);
    let isBulletList = $state(false);
    let isOrderedList = $state(false);
    let isH2 = $state(false);

    function updateToolbarState() {
        if (!editor) return;
        isBold = editor.isActive('bold');
        isItalic = editor.isActive('italic');
        isBulletList = editor.isActive('bulletList');
        isOrderedList = editor.isActive('orderedList');
        isH2 = editor.isActive('heading', { level: 2 });
    }

    onMount(() => {
        if (!features.richEditor || !editorElement) return;
        (async () => {
            const [{ Editor }, { default: StarterKit }] = await Promise.all([
                import('@tiptap/core'),
                import('@tiptap/starter-kit'),
            ]);
            if (!editorElement) return; // component unmounted while loading

            editor = new Editor({
                element: editorElement,
                extensions: [StarterKit],
                content,
                editable,
                onUpdate: ({ editor: e }) => {
                    updateToolbarState();
                    onchange?.(e.getHTML());
                },
                onSelectionUpdate: () => updateToolbarState(),
                onTransaction: () => updateToolbarState()
            });
            updateToolbarState();
        })();
    });

    onDestroy(() => {
        editor?.destroy();
    });
</script>

{#if !features.richEditor}
    <!-- ai-parrot: PUBLIC_AGENTCHAT_RICH_EDITOR=false — plain textarea, no @tiptap/* chunk. -->
    <textarea
        class="lite-editor-fallback {className}"
        style="--min-h: {minHeight}px"
        bind:value={plainContent}
        spellcheck="false"
        oninput={() => onchange?.(plainContent)}
        readonly={!editable}
    ></textarea>
{:else}
<div class="lite-editor {className}">
    {#if editable}
        <!-- Single toolbar row: Bold, Italic | H2 | Bullet, Ordered -->
        <div class="lite-toolbar">
            <div class="tgroup">
                <button
                    type="button"
                    class="tbtn"
                    class:active={isBold}
                    title="Bold"
                    onclick={() => editor?.chain().focus().toggleBold().run()}
                >
                    <Icon icon="mdi:format-bold" width="15" height="15" />
                </button>
                <button
                    type="button"
                    class="tbtn"
                    class:active={isItalic}
                    title="Italic"
                    onclick={() => editor?.chain().focus().toggleItalic().run()}
                >
                    <Icon icon="mdi:format-italic" width="15" height="15" />
                </button>
            </div>
            <span class="tdiv"></span>
            <div class="tgroup">
                <button
                    type="button"
                    class="tbtn"
                    class:active={isH2}
                    title="Heading 2"
                    onclick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
                >
                    <Icon icon="mdi:format-header-2" width="15" height="15" />
                </button>
            </div>
            <span class="tdiv"></span>
            <div class="tgroup">
                <button
                    type="button"
                    class="tbtn"
                    class:active={isBulletList}
                    title="Bullet List"
                    onclick={() => editor?.chain().focus().toggleBulletList().run()}
                >
                    <Icon icon="mdi:format-list-bulleted" width="15" height="15" />
                </button>
                <button
                    type="button"
                    class="tbtn"
                    class:active={isOrderedList}
                    title="Ordered List"
                    onclick={() => editor?.chain().focus().toggleOrderedList().run()}
                >
                    <Icon icon="mdi:format-list-numbered" width="15" height="15" />
                </button>
            </div>
        </div>
    {/if}

    <!-- Editor area with CSS-variable-driven min-height -->
    <div
        class="lite-content"
        style="--min-h: {minHeight}px"
        bind:this={editorElement}
    ></div>
</div>
{/if}

<style>
    .lite-editor-fallback {
        display: block;
        width: 100%;
        min-height: var(--min-h, 120px);
        padding: 0.5rem 0.75rem;
        border: 1px solid var(--border-color, #e5e7eb);
        border-radius: 0.5rem;
        background: var(--bg, #fff);
        color: var(--text, #1f2937);
        font-family: inherit;
        font-size: 0.875rem;
        resize: vertical;
    }

    :global(.dark) .lite-editor-fallback {
        border-color: var(--border-color-dark, #374151);
        background: var(--bg-dark, #1f2937);
        color: var(--text-dark, #e5e7eb);
    }

    .lite-editor {
        display: flex;
        flex-direction: column;
        border: 1px solid var(--border-color, #e5e7eb);
        border-radius: 0.5rem;
        overflow: hidden;
        background: var(--bg, #fff);
        transition: border-color 0.15s, box-shadow 0.15s;
    }

    :global(.dark) .lite-editor {
        border-color: var(--border-color-dark, #374151);
        background: var(--bg-dark, #1f2937);
    }

    .lite-editor:focus-within {
        border-color: oklch(56% 0.18 255);
        box-shadow: 0 0 0 1px oklch(56% 0.18 255 / 0.3);
    }

    /* ── Toolbar ── */
    .lite-toolbar {
        display: flex;
        align-items: center;
        gap: 0.125rem;
        padding: 0.25rem 0.375rem;
        border-bottom: 1px solid var(--border-color, #e5e7eb);
        background: var(--surface, #f9fafb);
    }

    :global(.dark) .lite-toolbar {
        border-color: var(--border-color-dark, #374151);
        background: var(--surface-dark, #111827);
    }

    .tgroup {
        display: flex;
        align-items: center;
        gap: 0.0625rem;
    }

    .tdiv {
        width: 1px;
        height: 1rem;
        background: var(--border-color, #e5e7eb);
        margin: 0 0.25rem;
    }

    :global(.dark) .tdiv {
        background: var(--border-color-dark, #374151);
    }

    .tbtn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.625rem;
        height: 1.625rem;
        border: none;
        border-radius: 0.25rem;
        background: transparent;
        color: var(--text, #374151);
        cursor: pointer;
        transition: background-color 0.15s;
    }

    .tbtn:hover {
        background: var(--hover-bg, #e5e7eb);
    }

    :global(.dark) .tbtn {
        color: var(--text-dark, #d1d5db);
    }

    :global(.dark) .tbtn:hover {
        background: var(--hover-bg-dark, #374151);
    }

    .tbtn.active {
        background: var(--active-bg, #dbeafe);
        color: var(--active-color, #2563eb);
    }

    :global(.dark) .tbtn.active {
        background: var(--active-bg-dark, #1e3a5f);
        color: var(--active-color-dark, #60a5fa);
    }

    /* ── Editor content area ── */
    .lite-content {
        overflow-y: auto;
    }

    .lite-content :global(.tiptap) {
        padding: 0.5rem 0.75rem;
        min-height: var(--min-h, 120px);
        outline: none;
        color: var(--text, #1f2937);
        font-size: 0.875rem;
        line-height: 1.6;
    }

    :global(.dark) .lite-content :global(.tiptap) {
        color: var(--text-dark, #e5e7eb);
    }

    .lite-content :global(.tiptap p) {
        margin: 0.2em 0;
    }

    .lite-content :global(.tiptap h2) {
        font-size: 0.9375rem;
        font-weight: 600;
        margin: 0.4em 0 0.2em;
        color: var(--text, #1f2937);
    }

    :global(.dark) .lite-content :global(.tiptap h2) {
        color: var(--text-dark, #e5e7eb);
    }

    .lite-content :global(.tiptap ul),
    .lite-content :global(.tiptap ol) {
        padding-left: 1.25rem;
        margin: 0.2em 0;
    }

    .lite-content :global(.tiptap ul) {
        list-style: disc;
    }

    .lite-content :global(.tiptap ol) {
        list-style: decimal;
    }

    .lite-content :global(.tiptap strong) {
        font-weight: 600;
    }

    .lite-content :global(.tiptap em) {
        font-style: italic;
    }

    /* Placeholder when empty */
    .lite-content :global(.tiptap p.is-editor-empty:first-child::before) {
        content: attr(data-placeholder);
        float: left;
        color: var(--placeholder, #9ca3af);
        pointer-events: none;
        height: 0;
    }
</style>
