<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Editor } from '@tiptap/core';
	import StarterKit from '@tiptap/starter-kit';
	import Link from '@tiptap/extension-link';
	import Underline from '@tiptap/extension-underline';
	import Icon from '@iconify/svelte';

	let { content, onUpdate }: { content: string; onUpdate: (html: string) => void } = $props();

	let editorEl = $state<HTMLDivElement | null>(null);
	let editor = $state<Editor | null>(null);

	// --- HTML document parsing utilities ---

	function extractHeadContent(html: string): string {
		const match = html.match(/<head[^>]*>([\s\S]*?)<\/head>/i);
		return match ? `<head>${match[1]}</head>` : '';
	}

	function extractBodyContent(html: string): string {
		const match = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
		return match ? match[1] : html;
	}

	function mergeHtmlDocument(head: string, body: string): string {
		return `<!DOCTYPE html><html>${head}<body>${body}</body></html>`;
	}

	// Preserved head across edits
	let preservedHead = extractHeadContent(content);

	onMount(() => {
		if (!editorEl) return;

		const bodyContent = extractBodyContent(content);

		editor = new Editor({
			element: editorEl,
			extensions: [
				StarterKit,
				Link.configure({ openOnClick: false }),
				Underline
			],
			content: bodyContent,
			onUpdate({ editor: e }) {
				const updatedBody = e.getHTML();
				onUpdate(mergeHtmlDocument(preservedHead, updatedBody));
			}
		});
	});

	onDestroy(() => {
		editor?.destroy();
	});

	// --- Toolbar helpers ---

	function isActive(type: string, attrs?: Record<string, unknown>): boolean {
		return editor?.isActive(type, attrs) ?? false;
	}

	function btnClass(active: boolean): string {
		return `btn btn-ghost btn-xs btn-square shrink-0 ${active ? 'bg-muted text-foreground' : ''}`;
	}

	function handleLink() {
		const url = window.prompt('URL:');
		if (url) {
			editor?.chain().focus().toggleLink({ href: url }).run();
		}
	}
</script>

<div class="flex flex-col h-full">
	<!-- Formatting toolbar -->
	<div class="flex items-center gap-0.5 px-2 py-1 border-b border-border bg-muted/10 overflow-x-auto shrink-0">
		<button
			class={btnClass(isActive('bold'))}
			onclick={() => editor?.chain().focus().toggleBold().run()}
			title="Bold"
		>
			<Icon icon="mdi:format-bold" class="size-4" />
		</button>
		<button
			class={btnClass(isActive('italic'))}
			onclick={() => editor?.chain().focus().toggleItalic().run()}
			title="Italic"
		>
			<Icon icon="mdi:format-italic" class="size-4" />
		</button>
		<button
			class={btnClass(isActive('underline'))}
			onclick={() => editor?.chain().focus().toggleUnderline().run()}
			title="Underline"
		>
			<Icon icon="mdi:format-underline" class="size-4" />
		</button>
		<button
			class={btnClass(isActive('strike'))}
			onclick={() => editor?.chain().focus().toggleStrike().run()}
			title="Strikethrough"
		>
			<Icon icon="mdi:format-strikethrough" class="size-4" />
		</button>

		<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

		<button
			class={btnClass(isActive('heading', { level: 1 })) + ' font-bold text-[11px]'}
			onclick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
			title="Heading 1"
		>H1</button>
		<button
			class={btnClass(isActive('heading', { level: 2 })) + ' font-bold text-[11px]'}
			onclick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
			title="Heading 2"
		>H2</button>
		<button
			class={btnClass(isActive('heading', { level: 3 })) + ' font-bold text-[11px]'}
			onclick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
			title="Heading 3"
		>H3</button>

		<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

		<button
			class={btnClass(isActive('bulletList'))}
			onclick={() => editor?.chain().focus().toggleBulletList().run()}
			title="Bullet list"
		>
			<Icon icon="mdi:format-list-bulleted" class="size-4" />
		</button>
		<button
			class={btnClass(isActive('orderedList'))}
			onclick={() => editor?.chain().focus().toggleOrderedList().run()}
			title="Ordered list"
		>
			<Icon icon="mdi:format-list-numbered" class="size-4" />
		</button>

		<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

		<button
			class={btnClass(isActive('link'))}
			onclick={handleLink}
			title="Link"
		>
			<Icon icon="mdi:link" class="size-4" />
		</button>
	</div>

	<!-- TipTap editor mount point -->
	<div
		bind:this={editorEl}
		class="flex-1 overflow-y-auto p-4 text-sm prose prose-sm dark:prose-invert max-w-none focus-within:outline-none [&_.ProseMirror]:outline-none [&_.ProseMirror]:min-h-full"
	></div>
</div>
