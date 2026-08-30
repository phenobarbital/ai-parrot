<script lang="ts">
  import { AppDialog } from "$lib/ui/components";
  import Icon from "@iconify/svelte";
  import type { Prompt } from "$lib/types/prompt-library";
  import {
    getPlaceholderOptions,
    insertPlaceholder,
  } from "$lib/utils/prompt-placeholders";
  import * as promptStore from "$lib/stores/prompt-library.svelte";
  import { toastStore } from "$lib/stores/toast.svelte";
  import MarkdownEditorToolbar from "./MarkdownEditorToolbar.svelte";

  let {
    open = $bindable(false),
    agentId,
    chatbotId,
    onSave,
    editPrompt = null,
  }: {
    open: boolean;
    agentId: string;
    chatbotId?: string;
    onSave?: (prompt: Prompt) => void;
    editPrompt?: Prompt | null;
  } = $props();

  // Panel state
  let selectedPromptId = $state<string | null>(null);
  let systemSectionOpen = $state(true);
  let userSectionOpen = $state(true);

  // Form state
  let title = $state("");
  let query = $state("");
  let isSaving = $state(false);
  let textareaRef = $state<HTMLTextAreaElement | null>(null);
  let cursorPosition = $state(0);
  let selectedPlaceholder = $state("");
  // Prompt pending delete confirmation. The confirm UI is a nested
  // AppDialog: the library modal is a Bits UI modal dialog, which blocks
  // pointer events outside its portal, so a sibling overlay never gets
  // clicks — nested Bits dialogs stack correctly instead.
  let deleteTarget = $state<Prompt | null>(null);
  let deleteDialogOpen = $state(false);
  let internalEditPrompt = $state<Prompt | null>(null);

  // Constants
  const MAX_TITLE_LENGTH = 50;
  const MAX_QUERY_LENGTH = 2000;

  // Computed values
  function getAllPrompts(): Prompt[] {
    return promptStore.getPrompts();
  }

  function getUserSectionPrompts(): Prompt[] {
    return promptStore.getUserPrompts();
  }

  function getPublicSectionPrompts(): Prompt[] {
    return promptStore.getPublicPrompts();
  }

  function getCanAddMore(): boolean {
    return promptStore.getCanAddMore();
  }

  function getUserPromptCount(): number {
    return promptStore.getUserPrompts().length;
  }

  function getIsLoading(): boolean {
    return promptStore.isLoadingPrompts();
  }

  // Derived
  let displayName = $derived(
    agentId
      .replace(/[_-]+/g, " ")
      .split(" ")
      .filter(Boolean)
      .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" "),
  );
  let placeholderOptions = $derived(getPlaceholderOptions());
  let currentEditPrompt = $derived(editPrompt ?? internalEditPrompt);
  let isEditing = $derived(currentEditPrompt !== null);
  // System (public) prompts open in a distinct read-only view instead of
  // the editor: plain-text fields, no toolbar/placeholders/save action.
  let isReadOnlyView = $derived(
    currentEditPrompt != null && !currentEditPrompt.is_user_prompt,
  );
  let isValid = $derived(
    title.trim().length > 0 &&
      title.trim().length <= MAX_TITLE_LENGTH &&
      query.trim().length > 0 &&
      query.trim().length <= MAX_QUERY_LENGTH,
  );
  let canSubmit = $derived(
    isValid && (isEditing || getCanAddMore()) && !isSaving,
  );

  // Initialize form when editPrompt changes or modal opens
  $effect(() => {
    if (open) {
      if (editPrompt) {
        title = editPrompt.title;
        query = editPrompt.query;
        internalEditPrompt = null;
        selectedPromptId = editPrompt.id;
      } else if (!internalEditPrompt) {
        // Reset for new prompt
        title = "";
        query = "";
        selectedPromptId = null;
      }
      selectedPlaceholder = "";
      deleteTarget = null;
      deleteDialogOpen = false;
    } else {
      internalEditPrompt = null;
      selectedPromptId = null;
    }
  });

  // Load prompts when modal opens
  $effect(() => {
    if (open && agentId) {
      promptStore.loadPrompts(agentId, chatbotId);
    }
  });

  function handleSelectPrompt(prompt: Prompt) {
    selectedPromptId = prompt.id;
    internalEditPrompt = prompt;
    title = prompt.title;
    query = prompt.query;
    deleteTarget = null;
    deleteDialogOpen = false;
  }

  function handleNewPrompt() {
    selectedPromptId = null;
    internalEditPrompt = null;
    title = "";
    query = "";
    deleteTarget = null;
    deleteDialogOpen = false;
  }

  function handleTextareaFocus() {
    if (textareaRef) {
      cursorPosition = textareaRef.selectionStart || 0;
    }
  }

  function handleTextareaClick() {
    if (textareaRef) {
      cursorPosition = textareaRef.selectionStart || 0;
    }
  }

  function handleTextareaKeyUp() {
    if (textareaRef) {
      cursorPosition = textareaRef.selectionStart || 0;
    }
  }

  function handlePlaceholderSelect() {
    if (!selectedPlaceholder || !textareaRef) return;

    const result = insertPlaceholder(
      query,
      cursorPosition,
      selectedPlaceholder,
    );
    query = result.text;
    selectedPlaceholder = "";

    requestAnimationFrame(() => {
      if (textareaRef) {
        textareaRef.focus();
        textareaRef.setSelectionRange(result.newCursorPos, result.newCursorPos);
        cursorPosition = result.newCursorPos;
      }
    });
  }

  async function handleSubmit() {
    if (!canSubmit) return;

    isSaving = true;

    try {
      let savedPrompt: Prompt;

      if (isEditing && currentEditPrompt) {
        if (!currentEditPrompt.is_user_prompt) {
          // Defensive: public prompts are read-only via this modal.
          return;
        }
        savedPrompt = await promptStore.updatePrompt({
          ...currentEditPrompt,
          title: title.trim(),
          query: query.trim(),
        });
        toastStore.success("Prompt updated successfully!");
        selectedPromptId = savedPrompt.id;
      } else {
        savedPrompt = await promptStore.addPrompt(
          agentId,
          title.trim(),
          query.trim(),
          chatbotId,
        );
        toastStore.success("Prompt saved successfully!");
        selectedPromptId = savedPrompt.id;
        internalEditPrompt = savedPrompt;
      }

      if (onSave) {
        onSave(savedPrompt);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      toastStore.error(`Failed to save prompt: ${message}`);
    } finally {
      isSaving = false;
    }
  }

  function requestDelete(prompt: Prompt) {
    deleteTarget = prompt;
    deleteDialogOpen = true;
  }

  async function confirmDelete() {
    const prompt = deleteTarget;
    if (!prompt) return;
    deleteDialogOpen = false;
    deleteTarget = null;

    try {
      await promptStore.removePrompt(prompt.id);
      toastStore.success("Prompt deleted successfully!");
      // If deleted the selected prompt, reset editor
      if (selectedPromptId === prompt.id) {
        handleNewPrompt();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      toastStore.error(`Failed to delete prompt: ${message}`);
    }
  }

  function cancelDelete() {
    deleteDialogOpen = false;
    deleteTarget = null;
  }

  function handleClose() {
    open = false;
    deleteTarget = null;
    deleteDialogOpen = false;
  }

  function truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength) + "...";
  }
</script>

<AppDialog
  bind:open
  eyebrow="Prompt Library"
  title={displayName}
  size="3xl"
  onclose={handleClose}
>
  <div
    class="flex flex-col md:flex-row gap-0 h-[520px] -mx-6 -my-4 overflow-hidden"
  >
    <!-- LEFT PANEL: Prompt list -->
    <div
      class="flex flex-col w-full md:w-[240px] md:min-w-[240px] border-b md:border-b-0 md:border-r border-base-200 bg-base-50 dark:bg-base-200/30 overflow-hidden"
    >
      <!-- Header + loading indicator -->
      <div
        class="flex items-center justify-between px-3 py-2 border-b border-base-200"
      >
        <span
          class="text-xs font-semibold text-base-content/60 uppercase tracking-wide"
        >
          Prompts
          {#if getIsLoading()}
            <Icon icon="mdi:loading" class="w-3 h-3 ml-1 inline animate-spin" />
          {/if}
        </span>
        <span class="text-xs text-base-content/40"
          >{getUserPromptCount()}/10</span
        >
      </div>

      <!-- Scrollable list -->
      <div class="flex-1 overflow-y-auto py-1">
        <!-- System Prompts (public, read-only) — listed first -->
        {#if getPublicSectionPrompts().length > 0}
          <button
            type="button"
            class="w-full flex items-center justify-between px-3 pt-2 pb-1 hover:bg-base-200/40 transition-colors"
            onclick={() => (systemSectionOpen = !systemSectionOpen)}
            aria-expanded={systemSectionOpen}
          >
            <span
              class="text-[10px] font-bold uppercase tracking-wider text-info flex items-center gap-1"
            >
              <Icon icon="mdi:lightbulb-outline" class="w-3 h-3" />
              System Prompts
              <span class="normal-case font-normal text-base-content/40">
                (read-only)
              </span>
            </span>
            <span class="flex items-center gap-1 text-base-content/40">
              {#if !systemSectionOpen}
                <span class="text-[10px] tabular-nums">
                  {getPublicSectionPrompts().length}
                </span>
              {/if}
              <Icon
                icon="mdi:chevron-down"
                class="w-3.5 h-3.5 transition-transform {systemSectionOpen
                  ? ''
                  : '-rotate-90'}"
              />
            </span>
          </button>
        {/if}
        {#if getPublicSectionPrompts().length > 0 && systemSectionOpen}
          {#each getPublicSectionPrompts() as prompt (prompt.id)}
            <button
              class="w-full text-left px-3 py-2 group flex items-start gap-2 transition-colors border-l-2 border-info/50 {selectedPromptId ===
              prompt.id
                ? 'bg-info/10 text-info'
                : 'hover:bg-info/5 text-base-content'}"
              onclick={() => handleSelectPrompt(prompt)}
            >
              <Icon
                icon="mdi:lightbulb-outline"
                class="w-3.5 h-3.5 mt-0.5 shrink-0 text-info"
              />
              <div class="min-w-0 flex-1">
                <div class="text-xs font-medium truncate">{prompt.title}</div>
                <div class="text-[10px] text-base-content/40 truncate">
                  {truncateText(prompt.query, 40)}
                </div>
              </div>
              <!-- No delete button — system prompts are read-only. -->
            </button>
          {/each}
        {/if}

        <!-- My Prompts (user-owned, editable) -->
        {#if getUserSectionPrompts().length > 0}
          <button
            type="button"
            class="w-full flex items-center justify-between px-3 pt-2 pb-1 hover:bg-base-200/40 transition-colors"
            onclick={() => (userSectionOpen = !userSectionOpen)}
            aria-expanded={userSectionOpen}
          >
            <span
              class="text-[10px] font-bold uppercase tracking-wider text-warning flex items-center gap-1"
            >
              <Icon icon="mdi:lock" class="w-3 h-3" />
              My Prompts
            </span>
            <span class="flex items-center gap-1 text-base-content/40">
              {#if !userSectionOpen}
                <span class="text-[10px] tabular-nums">
                  {getUserSectionPrompts().length}
                </span>
              {/if}
              <Icon
                icon="mdi:chevron-down"
                class="w-3.5 h-3.5 transition-transform {userSectionOpen
                  ? ''
                  : '-rotate-90'}"
              />
            </span>
          </button>
        {/if}
        {#if getUserSectionPrompts().length > 0 && userSectionOpen}
          {#each getUserSectionPrompts() as prompt (prompt.id)}
            <!-- Row wrapper: select and delete are sibling buttons (nesting
                 a button inside a button is invalid HTML). -->
            <div
              class="w-full group flex items-start transition-colors border-l-2 border-warning/50 {selectedPromptId ===
              prompt.id
                ? 'bg-warning/10 text-warning'
                : 'hover:bg-warning/5 text-base-content'}"
            >
              <button
                class="flex-1 min-w-0 text-left pl-3 py-2 flex items-start gap-2"
                onclick={() => handleSelectPrompt(prompt)}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  class="w-3.5 h-3.5 mt-0.5 shrink-0 text-warning"
                >
                  <path
                    fill-rule="evenodd"
                    d="M10 1a4.5 4.5 0 0 0-4.5 4.5V9H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-.5V5.5A4.5 4.5 0 0 0 10 1Zm3 8V5.5a3 3 0 1 0-6 0V9h6Z"
                    clip-rule="evenodd"
                  />
                </svg>
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-medium truncate">{prompt.title}</div>
                  <div class="text-[10px] text-base-content/40 truncate">
                    {truncateText(prompt.query, 40)}
                  </div>
                </div>
              </button>
              <!-- Delete button (opens confirmation dialog) -->
              <button
                class="btn btn-ghost btn-xs text-error opacity-0 group-hover:opacity-100 shrink-0 mt-1.5 mr-1.5"
                onclick={() => requestDelete(prompt)}
                title="Delete"
              >
                <Icon icon="mdi:trash-can-outline" class="w-3 h-3" />
              </button>
            </div>
          {/each}
        {/if}

        <!-- Empty state -->
        {#if getAllPrompts().length === 0 && !getIsLoading()}
          <div class="flex flex-col items-center px-3 py-12 text-center gap-2">
            <Icon
              icon="mdi:bookmark-outline"
              class="w-8 h-8 text-base-content/25"
            />
            <p class="text-xs font-medium text-base-content/60">
              No prompts yet
            </p>
            <p
              class="text-[10px] text-base-content/40 leading-relaxed max-w-[180px]"
            >
              Click "New Prompt" below to create your first one.
            </p>
          </div>
        {/if}
      </div>

      <!-- New Prompt button -->
      <div class="border-t border-base-200 p-2">
        <button
          type="button"
          class="btn btn-ghost btn-sm w-full gap-2 text-primary"
          onclick={handleNewPrompt}
          disabled={!getCanAddMore()}
        >
          <Icon icon="mdi:plus" class="w-4 h-4" />
          New Prompt
        </button>
      </div>
    </div>

    <!-- RIGHT PANEL: Editor -->
    <div class="flex flex-col flex-1 min-w-0 overflow-hidden">
      <div class="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {#if isReadOnlyView}
          <!-- READ-ONLY VIEW: system prompt -->
          <div
            class="flex items-center gap-2 rounded-lg bg-info/10 border border-info/30 px-3 py-2 text-xs text-info"
          >
            <Icon icon="mdi:lock-outline" class="w-4 h-4 shrink-0" />
            System prompt — read-only. It cannot be edited or deleted.
          </div>

          <div>
            <span
              class="block mb-1.5 text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Title
            </span>
            <div
              class="flex items-center gap-2 rounded-lg border border-dashed border-info/40 bg-info/5 px-3 py-2.5 text-sm text-base-content/80"
            >
              <Icon
                icon="mdi:lock-outline"
                class="w-3.5 h-3.5 shrink-0 text-info/70"
              />
              {title}
            </div>
          </div>

          <div>
            <span
              class="block mb-1.5 text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Prompt
            </span>
            <div
              class="rounded-lg border border-dashed border-info/40 bg-info/5 px-3 py-2.5 min-h-[160px] font-mono text-sm leading-relaxed whitespace-pre-wrap text-base-content/80"
            >
              {query}
            </div>
          </div>
        {:else}
        <!-- Title -->
        <div>
          <div class="flex items-baseline justify-between mb-1.5">
            <label
              for="prompt-title"
              class="text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Title
            </label>
            <span class="text-xs tabular-nums text-gray-400 dark:text-gray-500">
              {title.length}/{MAX_TITLE_LENGTH}
            </span>
          </div>
          <input
            id="prompt-title"
            type="text"
            placeholder="e.g. Monthly Revenue Report"
            class="input input-bordered w-full !h-10"
            bind:value={title}
            maxlength={MAX_TITLE_LENGTH}
          />
        </div>

        <!-- Query editor with markdown toolbar -->
        <div>
          <div class="flex items-baseline justify-between mb-1.5">
            <label
              for="prompt-query"
              class="text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Prompt
            </label>
            <span class="text-xs tabular-nums text-gray-400 dark:text-gray-500">
              {query.length}/{MAX_QUERY_LENGTH}
            </span>
          </div>

          <!-- Markdown toolbar wraps the textarea -->
          <div
            class="rounded-lg border border-gray-300 dark:border-gray-600 bg-base-100 overflow-hidden transition-shadow focus-within:border-primary-500 focus-within:ring-2 focus-within:ring-primary-500/20"
          >
            {#if textareaRef}
              <MarkdownEditorToolbar textarea={textareaRef} bind:text={query} />
            {/if}
            <textarea
              id="prompt-query"
              bind:this={textareaRef}
              bind:value={query}
              placeholder="Enter your prompt text here. Use placeholders like &#123;&#123;today&#125;&#125; for dynamic values..."
              class="w-full min-h-[160px] resize-y font-mono text-sm bg-transparent border-0 outline-none focus:ring-0 p-3 placeholder:font-sans placeholder:text-gray-400"
              maxlength={MAX_QUERY_LENGTH}
              onfocus={handleTextareaFocus}
              onclick={handleTextareaClick}
              onkeyup={handleTextareaKeyUp}
            ></textarea>
          </div>
        </div>

        <!-- Placeholder combobox -->
        <div>
          <label
            for="placeholder-select"
            class="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5"
          >
            <Icon icon="mdi:code-braces" class="w-4 h-4 text-gray-400" />
            Insert Placeholder
          </label>
          <select
            id="placeholder-select"
            class="select select-bordered w-full !h-10 !min-h-[2.5rem]"
            bind:value={selectedPlaceholder}
            onchange={handlePlaceholderSelect}
          >
            <option value="">Select placeholder to insert...</option>
            {#each placeholderOptions as opt}
              <option value={opt.key}>
                {opt.label} — {opt.preview}
              </option>
            {/each}
          </select>
          <p
            class="mt-1.5 text-xs text-gray-500 dark:text-gray-400 leading-relaxed"
          >
            Placeholders are replaced with live values when the prompt is used.
          </p>
        </div>
        {/if}
      </div>
    </div>
  </div>

  {#snippet footer()}
    <span class="mr-auto self-center text-xs text-base-content/50">
      {getUserPromptCount()}/10 used
      {#if !getCanAddMore() && !isEditing}
        <span class="text-warning ml-1">(limit reached)</span>
      {/if}
    </span>
    {#if isEditing}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        onclick={handleNewPrompt}
      >
        {isReadOnlyView ? "Back" : "Cancel Edit"}
      </button>
    {/if}
    <button type="button" class="btn btn-ghost btn-sm" onclick={handleClose}>
      Close
    </button>
    {#if isReadOnlyView}
      <span
        class="inline-flex items-center gap-1.5 self-center rounded-full bg-info/10 border border-info/30 px-3 py-1 text-xs text-info"
      >
        <Icon icon="mdi:lock-outline" class="w-3.5 h-3.5" />
        Read-only
      </span>
    {:else}
      <button
        type="button"
        class="btn btn-primary btn-sm"
        onclick={handleSubmit}
        disabled={!canSubmit}
      >
        {#if isSaving}
          <Icon icon="mdi:loading" class="w-4 h-4 animate-spin" />
        {:else}
          <Icon icon={isEditing ? "mdi:check" : "mdi:plus"} class="w-4 h-4" />
        {/if}
        {isEditing ? "Update" : "Save Prompt"}
      </button>
    {/if}
  {/snippet}
</AppDialog>

<!-- Delete confirmation (destructive action) — nested dialog -->
<AppDialog
  bind:open={deleteDialogOpen}
  title="Delete Prompt"
  size="sm"
  onclose={() => (deleteTarget = null)}
>
  <div class="flex items-start gap-3">
    <div class="rounded-full bg-error/10 p-2 shrink-0">
      <Icon icon="mdi:trash-can-outline" class="w-5 h-5 text-error" />
    </div>
    <p class="text-sm text-base-content/80 leading-relaxed pt-1.5">
      Delete <span class="font-semibold">"{deleteTarget?.title}"</span>?
      This action cannot be undone.
    </p>
  </div>

  {#snippet footer()}
    <button type="button" class="btn btn-ghost btn-sm" onclick={cancelDelete}>
      Cancel
    </button>
    <button type="button" class="btn btn-error btn-sm" onclick={confirmDelete}>
      <Icon icon="mdi:trash-can-outline" class="w-4 h-4" />
      Delete
    </button>
  {/snippet}
</AppDialog>
