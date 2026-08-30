<script lang="ts">
	import Icon from '@iconify/svelte';

	let {
		textareaSelector,
		content,
		onContentChange
	}: {
		textareaSelector: string;
		content: string;
		onContentChange: (newContent: string) => void;
	} = $props();

	function insertAtCursor(before: string, after: string = '') {
		const textarea = document.querySelector<HTMLTextAreaElement>(textareaSelector);
		if (!textarea) return;

		const start = textarea.selectionStart;
		const end = textarea.selectionEnd;
		const selected = content.slice(start, end);
		const replacement = before + (selected || 'text') + after;
		const newContent = content.slice(0, start) + replacement + content.slice(end);
		onContentChange(newContent);

		requestAnimationFrame(() => {
			textarea.focus();
			const newPos = start + before.length + (selected || 'text').length;
			textarea.selectionStart = newPos;
			textarea.selectionEnd = newPos;
		});
	}

	function handleBold() { insertAtCursor('**', '**'); }
	function handleItalic() { insertAtCursor('*', '*'); }
	function handleStrikethrough() { insertAtCursor('~~', '~~'); }
	function handleH1() { insertAtCursor('# '); }
	function handleH2() { insertAtCursor('## '); }
	function handleH3() { insertAtCursor('### '); }
	function handleInlineCode() { insertAtCursor('`', '`'); }
	function handleCodeBlock() { insertAtCursor('```\n', '\n```'); }
	function handleUL() { insertAtCursor('- '); }
	function handleOL() { insertAtCursor('1. '); }
	function handleBlockquote() { insertAtCursor('> '); }
	function handleLink() { insertAtCursor('[', '](https://)'); }
</script>

<div class="flex items-center px-2 py-1 gap-1 border-b border-border bg-muted/20 shrink-0 flex-wrap">
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleBold} title="Bold">
		<Icon icon="mdi:format-bold" class="size-4" />
	</button>
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleItalic} title="Italic">
		<Icon icon="mdi:format-italic" class="size-4" />
	</button>
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleStrikethrough} title="Strikethrough">
		<Icon icon="mdi:format-strikethrough" class="size-4" />
	</button>

	<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

	<button class="btn btn-ghost btn-xs btn-square font-bold text-[11px] shrink-0" onclick={handleH1} title="Heading 1">H1</button>
	<button class="btn btn-ghost btn-xs btn-square font-bold text-[11px] shrink-0" onclick={handleH2} title="Heading 2">H2</button>
	<button class="btn btn-ghost btn-xs btn-square font-bold text-[11px] shrink-0" onclick={handleH3} title="Heading 3">H3</button>

	<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleUL} title="Unordered list">
		<Icon icon="mdi:format-list-bulleted" class="size-4" />
	</button>
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleOL} title="Ordered list">
		<Icon icon="mdi:format-list-numbered" class="size-4" />
	</button>

	<div class="w-px h-4 bg-border mx-0.5 shrink-0"></div>

	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleInlineCode} title="Inline code">
		<Icon icon="mdi:code-tags" class="size-4" />
	</button>
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleCodeBlock} title="Code block">
		<Icon icon="mdi:code-braces" class="size-4" />
	</button>
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleBlockquote} title="Blockquote">
		<Icon icon="mdi:format-quote-open" class="size-4" />
	</button>
	<button class="btn btn-ghost btn-xs btn-square shrink-0" onclick={handleLink} title="Link">
		<Icon icon="mdi:link" class="size-4" />
	</button>
</div>
