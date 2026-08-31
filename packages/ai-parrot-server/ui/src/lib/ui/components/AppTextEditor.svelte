<script lang="ts">
    /**
     * AppTextEditor — Rich text editor wrapper using TipTap v3.
     * Replaces @flowbite-svelte-plugins/texteditor.
     *
     * Supports HTML editing with a configurable toolbar.
     *
     * ai-parrot (FEAT-476 TASK-2593): the `@tiptap/*` packages are loaded
     * only behind `features.richEditor` — a static import from an
     * always-on file would defeat the build-time flag (spec §7 "Flag
     * gating"). When the flag is off, this renders a plain `<textarea>`
     * fallback instead of the toolbar/editor.
     */
    import { onMount, onDestroy } from "svelte";
    import Icon from "@iconify/svelte";
    import { features } from "$lib/features";
    import type { Editor as TiptapEditor } from "@tiptap/core";

    interface Props {
        content?: string;
        editable?: boolean;
        onchange?: (html: string) => void;
        class?: string;
    }

    let {
        content = "",
        editable = true,
        onchange,
        class: className = "",
    }: Props = $props();

    let editorElement: HTMLDivElement | undefined = $state();
    let editor: TiptapEditor | undefined = $state();
    let sourceMode = $state(false);
    let sourceHtml = $state("");
    // Plain-textarea fallback content, kept in sync with `content` when
    // features.richEditor is off.
    let plainContent = $state(content);

    // Toolbar state — derived from editor
    let isBold = $state(false);
    let isItalic = $state(false);
    let isStrike = $state(false);
    let isBulletList = $state(false);
    let isOrderedList = $state(false);
    let isBlockquote = $state(false);
    let isCodeBlock = $state(false);
    let activeHeading = $state(0);
    let activeAlign = $state("left");

    function updateToolbarState() {
        if (!editor) return;
        isBold = editor.isActive("bold");
        isItalic = editor.isActive("italic");
        isStrike = editor.isActive("strike");
        isBulletList = editor.isActive("bulletList");
        isOrderedList = editor.isActive("orderedList");
        isBlockquote = editor.isActive("blockquote");
        isCodeBlock = editor.isActive("codeBlock");
        activeHeading = editor.isActive("heading", { level: 1 })
            ? 1
            : editor.isActive("heading", { level: 2 })
              ? 2
              : editor.isActive("heading", { level: 3 })
                ? 3
                : 0;
        activeAlign = editor.isActive({ textAlign: "center" })
            ? "center"
            : editor.isActive({ textAlign: "right" })
              ? "right"
              : editor.isActive({ textAlign: "justify" })
                ? "justify"
                : "left";
    }

    onMount(() => {
        if (!features.richEditor || !editorElement) return;

        (async () => {
            const [{ Editor }, { default: StarterKit }, { default: TextAlign }, { TextStyle }, { default: Typography }] =
                await Promise.all([
                    import("@tiptap/core"),
                    import("@tiptap/starter-kit"),
                    import("@tiptap/extension-text-align"),
                    import("@tiptap/extension-text-style"),
                    import("@tiptap/extension-typography"),
                ]);

            if (!editorElement) return; // component unmounted while loading

            editor = new Editor({
                element: editorElement,
                extensions: [
                    StarterKit,
                    TextStyle,
                    Typography,
                    TextAlign.configure({
                        types: ["heading", "paragraph"],
                    }),
                ],
                content,
                editable,
                onUpdate: ({ editor: e }) => {
                    updateToolbarState();
                    onchange?.(e.getHTML());
                },
                onSelectionUpdate: () => {
                    updateToolbarState();
                },
                onTransaction: () => {
                    updateToolbarState();
                },
            });

            updateToolbarState();
        })();
    });

    onDestroy(() => {
        editor?.destroy();
    });

    function toggleSource() {
        if (!editor) return;
        if (!sourceMode) {
            sourceHtml = editor.getHTML();
            sourceMode = true;
        } else {
            editor.commands.setContent(sourceHtml);
            sourceMode = false;
            onchange?.(sourceHtml);
        }
    }

    function applySourceChanges() {
        if (!editor) return;
        editor.commands.setContent(sourceHtml);
        sourceMode = false;
        onchange?.(sourceHtml);
    }

    // Toolbar button definitions
    type ToolbarButton = {
        icon: string;
        title: string;
        action: () => void;
        isActive: () => boolean;
    };

    function getFormatButtons(): ToolbarButton[] {
        return [
            {
                icon: "mdi:format-bold",
                title: "Bold",
                action: () => editor?.chain().focus().toggleBold().run(),
                isActive: () => isBold,
            },
            {
                icon: "mdi:format-italic",
                title: "Italic",
                action: () => editor?.chain().focus().toggleItalic().run(),
                isActive: () => isItalic,
            },
            {
                icon: "mdi:format-strikethrough",
                title: "Strikethrough",
                action: () => editor?.chain().focus().toggleStrike().run(),
                isActive: () => isStrike,
            },
        ];
    }

    function getHeadingButtons(): ToolbarButton[] {
        return [
            {
                icon: "mdi:format-header-1",
                title: "Heading 1",
                action: () =>
                    editor?.chain().focus().toggleHeading({ level: 1 }).run(),
                isActive: () => activeHeading === 1,
            },
            {
                icon: "mdi:format-header-2",
                title: "Heading 2",
                action: () =>
                    editor?.chain().focus().toggleHeading({ level: 2 }).run(),
                isActive: () => activeHeading === 2,
            },
            {
                icon: "mdi:format-header-3",
                title: "Heading 3",
                action: () =>
                    editor?.chain().focus().toggleHeading({ level: 3 }).run(),
                isActive: () => activeHeading === 3,
            },
        ];
    }

    function getListButtons(): ToolbarButton[] {
        return [
            {
                icon: "mdi:format-list-bulleted",
                title: "Bullet List",
                action: () =>
                    editor?.chain().focus().toggleBulletList().run(),
                isActive: () => isBulletList,
            },
            {
                icon: "mdi:format-list-numbered",
                title: "Ordered List",
                action: () =>
                    editor?.chain().focus().toggleOrderedList().run(),
                isActive: () => isOrderedList,
            },
        ];
    }

    function getAlignButtons(): ToolbarButton[] {
        return [
            {
                icon: "mdi:format-align-left",
                title: "Align Left",
                action: () =>
                    editor?.chain().focus().setTextAlign("left").run(),
                isActive: () => activeAlign === "left",
            },
            {
                icon: "mdi:format-align-center",
                title: "Align Center",
                action: () =>
                    editor?.chain().focus().setTextAlign("center").run(),
                isActive: () => activeAlign === "center",
            },
            {
                icon: "mdi:format-align-right",
                title: "Align Right",
                action: () =>
                    editor?.chain().focus().setTextAlign("right").run(),
                isActive: () => activeAlign === "right",
            },
            {
                icon: "mdi:format-align-justify",
                title: "Justify",
                action: () =>
                    editor?.chain().focus().setTextAlign("justify").run(),
                isActive: () => activeAlign === "justify",
            },
        ];
    }

    function getBlockButtons(): ToolbarButton[] {
        return [
            {
                icon: "mdi:format-quote-close",
                title: "Blockquote",
                action: () =>
                    editor?.chain().focus().toggleBlockquote().run(),
                isActive: () => isBlockquote,
            },
            {
                icon: "mdi:code-braces",
                title: "Code Block",
                action: () =>
                    editor?.chain().focus().toggleCodeBlock().run(),
                isActive: () => isCodeBlock,
            },
            {
                icon: "mdi:minus",
                title: "Horizontal Rule",
                action: () =>
                    editor?.chain().focus().setHorizontalRule().run(),
                isActive: () => false,
            },
        ];
    }
</script>

{#if !features.richEditor}
    <!-- ai-parrot: PUBLIC_AGENTCHAT_RICH_EDITOR=false — plain textarea, no @tiptap/* chunk. -->
    <textarea
        class="app-text-editor-fallback {className}"
        bind:value={plainContent}
        spellcheck="false"
        oninput={() => onchange?.(plainContent)}
        readonly={!editable}
    ></textarea>
{:else}
<div class="app-text-editor {className}">
    <!-- Toolbar Row 1: Format, Headings, Lists -->
    <div class="editor-toolbar">
        <div class="toolbar-group">
            {#each getFormatButtons() as btn (btn.title)}
                <button
                    type="button"
                    class="toolbar-btn"
                    class:active={btn.isActive()}
                    title={btn.title}
                    onclick={btn.action}
                >
                    <Icon icon={btn.icon} width="18" height="18" />
                </button>
            {/each}
        </div>
        <span class="toolbar-divider"></span>
        <div class="toolbar-group">
            {#each getHeadingButtons() as btn (btn.title)}
                <button
                    type="button"
                    class="toolbar-btn"
                    class:active={btn.isActive()}
                    title={btn.title}
                    onclick={btn.action}
                >
                    <Icon icon={btn.icon} width="18" height="18" />
                </button>
            {/each}
        </div>
        <span class="toolbar-divider"></span>
        <div class="toolbar-group">
            {#each getListButtons() as btn (btn.title)}
                <button
                    type="button"
                    class="toolbar-btn"
                    class:active={btn.isActive()}
                    title={btn.title}
                    onclick={btn.action}
                >
                    <Icon icon={btn.icon} width="18" height="18" />
                </button>
            {/each}
        </div>
    </div>

    <!-- Toolbar Row 2: Undo/Redo, Alignment, Blocks, Source -->
    <div class="editor-toolbar">
        <div class="toolbar-group">
            <button
                type="button"
                class="toolbar-btn"
                title="Undo"
                onclick={() => editor?.chain().focus().undo().run()}
            >
                <Icon icon="mdi:undo" width="18" height="18" />
            </button>
            <button
                type="button"
                class="toolbar-btn"
                title="Redo"
                onclick={() => editor?.chain().focus().redo().run()}
            >
                <Icon icon="mdi:redo" width="18" height="18" />
            </button>
        </div>
        <span class="toolbar-divider"></span>
        <div class="toolbar-group">
            {#each getAlignButtons() as btn (btn.title)}
                <button
                    type="button"
                    class="toolbar-btn"
                    class:active={btn.isActive()}
                    title={btn.title}
                    onclick={btn.action}
                >
                    <Icon icon={btn.icon} width="18" height="18" />
                </button>
            {/each}
        </div>
        <span class="toolbar-divider"></span>
        <div class="toolbar-group">
            {#each getBlockButtons() as btn (btn.title)}
                <button
                    type="button"
                    class="toolbar-btn"
                    class:active={btn.isActive()}
                    title={btn.title}
                    onclick={btn.action}
                >
                    <Icon icon={btn.icon} width="18" height="18" />
                </button>
            {/each}
        </div>
        <span class="toolbar-divider"></span>
        <div class="toolbar-group">
            <button
                type="button"
                class="toolbar-btn"
                class:active={sourceMode}
                title="View Source"
                onclick={toggleSource}
            >
                <Icon icon="mdi:code-tags" width="18" height="18" />
            </button>
        </div>
    </div>

    <!-- Editor or Source view -->
    {#if sourceMode}
        <div class="source-editor">
            <textarea
                class="source-textarea"
                bind:value={sourceHtml}
                spellcheck="false"
            ></textarea>
            <div class="source-actions">
                <button
                    type="button"
                    class="btn btn-sm btn-primary"
                    onclick={applySourceChanges}
                >
                    Apply
                </button>
                <button
                    type="button"
                    class="btn btn-sm"
                    onclick={() => (sourceMode = false)}
                >
                    Cancel
                </button>
            </div>
        </div>
    {:else}
        <div class="editor-content" bind:this={editorElement}></div>
    {/if}
</div>
{/if}

<style>
    .app-text-editor-fallback {
        display: block;
        width: 100%;
        min-height: 250px;
        padding: 1rem;
        border: 1px solid var(--border-color, #e5e7eb);
        border-radius: 0.5rem;
        background: var(--bg, #fff);
        color: var(--text, #1f2937);
        font-family: inherit;
        resize: vertical;
    }

    :global(.dark) .app-text-editor-fallback {
        border-color: var(--border-color-dark, #374151);
        background: var(--bg-dark, #1f2937);
        color: var(--text-dark, #e5e7eb);
    }

    .app-text-editor {
        display: flex;
        flex-direction: column;
        border: 1px solid var(--border-color, #e5e7eb);
        border-radius: 0.5rem;
        overflow: hidden;
        background: var(--bg, #fff);
    }

    :global(.dark) .app-text-editor {
        border-color: var(--border-color-dark, #374151);
        background: var(--bg-dark, #1f2937);
    }

    .editor-toolbar {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.375rem 0.5rem;
        border-bottom: 1px solid var(--border-color, #e5e7eb);
        background: var(--surface, #f9fafb);
        flex-wrap: wrap;
    }

    :global(.dark) .editor-toolbar {
        border-color: var(--border-color-dark, #374151);
        background: var(--surface-dark, #111827);
    }

    .toolbar-group {
        display: flex;
        align-items: center;
        gap: 0.125rem;
    }

    .toolbar-divider {
        width: 1px;
        height: 1.25rem;
        background: var(--border-color, #e5e7eb);
        margin: 0 0.25rem;
    }

    :global(.dark) .toolbar-divider {
        background: var(--border-color-dark, #374151);
    }

    .toolbar-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2rem;
        height: 2rem;
        border: none;
        border-radius: 0.25rem;
        background: transparent;
        color: var(--text, #374151);
        cursor: pointer;
        transition: background-color 0.15s;
    }

    .toolbar-btn:hover {
        background: var(--hover-bg, #e5e7eb);
    }

    :global(.dark) .toolbar-btn {
        color: var(--text-dark, #d1d5db);
    }

    :global(.dark) .toolbar-btn:hover {
        background: var(--hover-bg-dark, #374151);
    }

    .toolbar-btn.active {
        background: var(--active-bg, #dbeafe);
        color: var(--active-color, #2563eb);
    }

    :global(.dark) .toolbar-btn.active {
        background: var(--active-bg-dark, #1e3a5f);
        color: var(--active-color-dark, #60a5fa);
    }

    .editor-content {
        flex: 1;
        min-height: 250px;
        overflow-y: auto;
    }

    .editor-content :global(.tiptap) {
        padding: 1rem;
        min-height: 250px;
        outline: none;
        color: var(--text, #1f2937);
    }

    :global(.dark) .editor-content :global(.tiptap) {
        color: var(--text-dark, #e5e7eb);
    }

    .editor-content :global(.tiptap p) {
        margin: 0.5em 0;
    }

    .editor-content :global(.tiptap h1) {
        font-size: 1.75rem;
        font-weight: 700;
        margin: 0.75em 0 0.5em;
    }

    .editor-content :global(.tiptap h2) {
        font-size: 1.5rem;
        font-weight: 600;
        margin: 0.75em 0 0.5em;
    }

    .editor-content :global(.tiptap h3) {
        font-size: 1.25rem;
        font-weight: 600;
        margin: 0.75em 0 0.5em;
    }

    .editor-content :global(.tiptap blockquote) {
        border-left: 3px solid var(--border-color, #e5e7eb);
        padding-left: 1rem;
        margin: 0.5em 0;
        font-style: italic;
        color: var(--text-secondary, #6b7280);
    }

    .editor-content :global(.tiptap code) {
        background: var(--code-bg, #f3f4f6);
        padding: 0.125rem 0.25rem;
        border-radius: 0.25rem;
        font-size: 0.875em;
    }

    .editor-content :global(.tiptap pre) {
        background: var(--code-bg, #1e1e1e);
        color: var(--code-color, #d4d4d4);
        padding: 0.75rem 1rem;
        border-radius: 0.375rem;
        overflow-x: auto;
        margin: 0.5em 0;
    }

    .editor-content :global(.tiptap pre code) {
        background: none;
        padding: 0;
    }

    .editor-content :global(.tiptap ul),
    .editor-content :global(.tiptap ol) {
        padding-left: 1.5rem;
        margin: 0.5em 0;
    }

    .editor-content :global(.tiptap ul) {
        list-style: disc;
    }

    .editor-content :global(.tiptap ol) {
        list-style: decimal;
    }

    .editor-content :global(.tiptap hr) {
        border: none;
        border-top: 1px solid var(--border-color, #e5e7eb);
        margin: 1em 0;
    }

    .source-editor {
        flex: 1;
        display: flex;
        flex-direction: column;
    }

    .source-textarea {
        flex: 1;
        min-height: 250px;
        padding: 1rem;
        border: none;
        outline: none;
        resize: none;
        font-family: "Fira Code", "Cascadia Code", monospace;
        font-size: 0.875rem;
        line-height: 1.5;
        background: var(--code-bg, #1e1e1e);
        color: var(--code-color, #d4d4d4);
    }

    .source-actions {
        display: flex;
        gap: 0.5rem;
        padding: 0.5rem;
        border-top: 1px solid var(--border-color, #e5e7eb);
        background: var(--surface, #f9fafb);
    }

    :global(.dark) .source-actions {
        border-color: var(--border-color-dark, #374151);
        background: var(--surface-dark, #111827);
    }
</style>
