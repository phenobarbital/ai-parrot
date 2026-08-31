<script lang="ts">
  interface Props {
    textarea: HTMLTextAreaElement;
    text: string;
  }

  let { textarea = $bindable(), text = $bindable() }: Props = $props();

  /**
   * Insert markdown syntax around selected text or at cursor.
   * If text is selected, wraps it; otherwise inserts prefix+suffix and places cursor between.
   */
  function insertMarkdown(prefix: string, suffix: string = "") {
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = text.slice(start, end);

    let newText: string;
    let newCursorPos: number;

    if (selected) {
      // Wrap selection
      newText = text.slice(0, start) + prefix + selected + suffix + text.slice(end);
      newCursorPos = start + prefix.length + selected.length + suffix.length;
    } else {
      // Insert at cursor and place cursor between prefix and suffix
      newText = text.slice(0, start) + prefix + suffix + text.slice(end);
      newCursorPos = start + prefix.length;
    }

    text = newText;

    // Restore focus and set cursor position after Svelte updates the DOM
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    });
  }

  /**
   * Insert a list prefix at the beginning of the current line.
   */
  function insertLinePrefix(prefix: string) {
    if (!textarea) return;

    const start = textarea.selectionStart;
    // Find start of current line
    const lineStart = text.lastIndexOf("\n", start - 1) + 1;
    const newText = text.slice(0, lineStart) + prefix + text.slice(lineStart);
    text = newText;

    const newCursorPos = start + prefix.length;
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    });
  }

  /**
   * Insert a code block — inline backticks for single-line, triple for multi-line.
   */
  function insertCode() {
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = text.slice(start, end);
    const isMultiLine = selected.includes("\n");

    if (isMultiLine) {
      insertMarkdown("```\n", "\n```");
    } else {
      insertMarkdown("`", "`");
    }
  }

  /**
   * Insert a link template.
   */
  function insertLink() {
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = text.slice(start, end);

    if (selected) {
      // Wrap selected text as link label
      const newText = text.slice(0, start) + `[${selected}](url)` + text.slice(end);
      text = newText;
      const newCursorPos = start + selected.length + 3; // position at "url"
      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(newCursorPos, newCursorPos + 3);
      });
    } else {
      insertMarkdown("[", "](url)");
    }
  }
</script>

<div
  class="flex items-center gap-0.5 px-2 py-1 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 rounded-t-lg"
  role="toolbar"
  aria-label="Markdown formatting toolbar"
>
  <!-- Bold -->
  <button
    type="button"
    class="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-800 hover:bg-slate-200 dark:hover:text-slate-200 dark:hover:bg-slate-700 transition-colors font-bold text-sm"
    title="Bold (Ctrl+B)"
    onclick={() => insertMarkdown("**", "**")}
    onmousedown={(e) => e.preventDefault()}
  >
    B
  </button>

  <!-- Italic -->
  <button
    type="button"
    class="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-800 hover:bg-slate-200 dark:hover:text-slate-200 dark:hover:bg-slate-700 transition-colors italic text-sm"
    title="Italic (Ctrl+I)"
    onclick={() => insertMarkdown("*", "*")}
    onmousedown={(e) => e.preventDefault()}
  >
    I
  </button>

  <div class="w-px h-4 bg-slate-300 dark:bg-slate-600 mx-0.5"></div>

  <!-- Bullet List -->
  <button
    type="button"
    class="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-800 hover:bg-slate-200 dark:hover:text-slate-200 dark:hover:bg-slate-700 transition-colors"
    title="Bullet list"
    onclick={() => insertLinePrefix("- ")}
    onmousedown={(e) => e.preventDefault()}
  >
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="h-3.5 w-3.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0z" />
    </svg>
  </button>

  <!-- Numbered List -->
  <button
    type="button"
    class="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-800 hover:bg-slate-200 dark:hover:text-slate-200 dark:hover:bg-slate-700 transition-colors text-xs font-medium"
    title="Numbered list"
    onclick={() => insertLinePrefix("1. ")}
    onmousedown={(e) => e.preventDefault()}
  >
    1.
  </button>

  <div class="w-px h-4 bg-slate-300 dark:bg-slate-600 mx-0.5"></div>

  <!-- Link -->
  <button
    type="button"
    class="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-800 hover:bg-slate-200 dark:hover:text-slate-200 dark:hover:bg-slate-700 transition-colors"
    title="Insert link"
    onclick={insertLink}
    onmousedown={(e) => e.preventDefault()}
  >
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="h-3.5 w-3.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
    </svg>
  </button>

  <!-- Code -->
  <button
    type="button"
    class="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-800 hover:bg-slate-200 dark:hover:text-slate-200 dark:hover:bg-slate-700 transition-colors"
    title="Code block"
    onclick={insertCode}
    onmousedown={(e) => e.preventDefault()}
  >
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="h-3.5 w-3.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5" />
    </svg>
  </button>
</div>
