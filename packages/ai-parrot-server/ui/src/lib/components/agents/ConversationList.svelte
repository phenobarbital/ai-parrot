<script lang="ts">
  import { onMount } from "svelte";
  import { ChatService } from "$lib/services/chat-db";
  import type { AgentConversation } from "$lib/types/agent";
  import { liveQuery } from "dexie";
  import { AppTooltip, AppDropdown, AppDropdownItem } from "$lib/ui/components";
  import Icon from "@iconify/svelte";

  let {
    agentId,
    currentSessionId,
    onSelect,
    onNew,
    compact = false,
    onToggleSidebar,
  } = $props<{
    agentId: string;
    currentSessionId: string | null;
    onSelect: (id: string) => void;
    onNew: () => void;
    compact?: boolean;
    onToggleSidebar?: () => void;
  }>();

  // Live query for conversations (watches Dexie only for reactivity)
  let conversations = $state<AgentConversation[]>([]);

  $effect(() => {
    const sub = liveQuery(() =>
      ChatService._getLocalConversations(agentId),
    ).subscribe({
      next: (value) => {
        console.log("[ConversationList] Conversations updated:", value.length);
        conversations = value;
      },
      error: (err) => console.error("[ConversationList] Query Error:", err),
    });
    return () => sub.unsubscribe();
  });

  // Sync from backend on mount (upserts into Dexie → triggers liveQuery)
  onMount(() => {
    ChatService.syncConversationsFromBackend(agentId);
  });

  function formatTime(date: Date): string {
    const d = new Date(date);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    } else if (diffDays < 7) {
      return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
    } else {
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }
  }

  // Helper: comparación segura de IDs (string vs number safe)
  function isActive(convId: string): boolean {
    return (
      currentSessionId != null && String(currentSessionId) === String(convId)
    );
  }

  // Delete modal state
  let deleteModalOpen = $state(false);
  let deleteTargetId = $state<string | null>(null);
  let isDeletingAll = $state(false);
  let deleteModal: HTMLDialogElement;

  // Editing state
  let editingId = $state<string | null>(null);
  let editTitle = $state("");

  function startEditing(id: string, currentTitle: string, e: MouseEvent) {
    e.stopPropagation();
    editingId = id;
    editTitle = currentTitle;
  }

  async function saveTitle() {
    if (editingId && editTitle.trim()) {
      await ChatService.updateConversationTitle(editingId, editTitle.trim(), agentId);
      // No need to manually update local list as liveQuery handles it
    }
    editingId = null;
    editTitle = "";
  }

  function cancelEditing() {
    editingId = null;
    editTitle = "";
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      saveTitle();
    } else if (e.key === "Escape") {
      cancelEditing();
    }
  }

  $effect(() => {
    if (deleteModalOpen && deleteModal) {
      deleteModal.showModal();
    } else if (deleteModal) {
      deleteModal.close();
    }
  });

  function promptDelete(id: string, e: MouseEvent) {
    e.stopPropagation();
    deleteTargetId = id;
    isDeletingAll = false;
    deleteModalOpen = true;
  }

  function promptDeleteAll() {
    isDeletingAll = true;
    deleteModalOpen = true;
  }

  async function confirmDelete() {
    if (isDeletingAll) {
      onNew(); // Reset to new conversation BEFORE clearing all
      await ChatService.clearHistory();
    } else if (deleteTargetId) {
      // Si borro la conversación activa, reseteo la vista PRIMERO
      if (isActive(deleteTargetId)) {
        onNew();
      }
      await ChatService.deleteConversation(deleteTargetId, agentId);
    }
    deleteModalOpen = false;
    deleteTargetId = null;
    isDeletingAll = false;
  }

  async function handleRefresh() {
    // Sync from backend first, then Dexie liveQuery will auto-update
    await ChatService.syncConversationsFromBackend(agentId);
    // Manual fallback in case liveQuery lags
    const recent = await ChatService._getLocalConversations(agentId);
    conversations = recent;
  }
</script>

<div
  class={`bg-card border-border flex h-full min-h-0 flex-col border-r transition-all duration-300 ${compact ? "w-16 items-center" : ""}`}
>
  <div
    class="flex items-center justify-between px-3 h-9 border-b border-border shrink-0 select-none"
  >
    <span
      class={`text-[10px] font-bold text-slate-400 uppercase tracking-wider ${compact ? "hidden" : "block"}`}
    >
      History
    </span>
    <div class="flex items-center gap-1">
      <button
        class="btn btn-ghost btn-xs btn-circle h-7 w-7 min-h-0 text-slate-400 hover:text-blue-500"
        onclick={handleRefresh}
        title="Refresh conversations"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="size-4"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
          />
        </svg>
      </button>
      {#if conversations.length > 0 && !compact}
        <button
          class="btn btn-ghost btn-xs btn-circle h-7 w-7 min-h-0 text-slate-400 hover:text-error"
          onclick={promptDeleteAll}
          title="Delete all conversations"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="size-4"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
            />
          </svg>
        </button>
      {/if}
      {#if onToggleSidebar}
        <button
          class="btn btn-ghost btn-xs btn-circle h-7 w-7 min-h-0 text-slate-400 hover:text-slate-600"
          onclick={onToggleSidebar}
          title={compact ? "Expand" : "Collapse"}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="size-4"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d={compact
                ? "M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3"
                : "M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18"}
            />
          </svg>
        </button>
      {/if}
    </div>
  </div>

  <div
    class={`conversation-list-scroll flex-1 flex flex-col space-y-0.5 overflow-y-auto overflow-x-hidden min-h-0 min-w-0 ${compact ? "w-full items-center px-1" : "px-2"}`}
  >
    {#if conversations.length === 0}
      {#if !compact}
        <div
          class="flex flex-col items-center justify-center py-12 gap-2 opacity-50"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="size-8 text-muted-foreground"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 1-.825-.242m9.345-8.334a2.126 2.126 0 0 0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155"
            />
          </svg>
          <p class="text-xs text-muted-foreground">No conversations yet</p>
        </div>
      {/if}
    {/if}

    {#each conversations as conv (conv.id)}
      <div class="group relative w-full min-w-0 mb-1">
        {#if editingId === conv.id}
          <!-- Edit Mode -->
          <div
            class={`flex w-full min-w-0 flex-col gap-0.5 rounded-xl p-2 transition-colors duration-200 ${isActive(conv.id) ? "bg-primary/10 border-l-2 border-primary" : "bg-gray-100 dark:bg-gray-800 border-l-2 border-transparent"} ${compact ? "items-center justify-center" : ""}`}
          >
            <input
              type="text"
              bind:value={editTitle}
              class="input input-xs input-bordered w-full text-xs h-6 px-1"
              autofocus
              onblur={saveTitle}
              onkeydown={handleKeydown}
              onclick={(e) => e.stopPropagation()}
            />
          </div>
        {:else}
          <!-- View Mode -->
          <button
            id="conv-{conv.id}"
            class={`flex w-full min-w-0 flex-col gap-0.5 rounded-lg px-3 py-2.5 text-left transition-all duration-150 ${
              isActive(conv.id)
                ? "bg-primary text-primary-foreground font-semibold shadow-md shadow-primary/30"
                : "text-foreground/70 hover:bg-foreground/5 hover:text-foreground"
            } ${compact ? "items-center justify-center" : ""}`}
            onclick={() => onSelect(conv.id)}
            title={compact ? conv.title : undefined}
          >
            {#if compact}
              <!-- Compact View: Initials or Icon -->
              <div
                class={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold ${isActive(conv.id) ? "bg-primary/20 text-primary ring-1 ring-primary/40" : "bg-primary/10 text-primary"}`}
              >
                {conv.title.substring(0, 2).toUpperCase()}
              </div>
            {:else}
              <!-- Full View -->
              <span class="block w-full truncate text-xs {isActive(conv.id) ? 'font-semibold' : 'font-normal'}">{conv.title}</span>
              <div class="flex w-full items-center justify-between">
                <span class="max-w-[120px] truncate text-[11px] opacity-50"
                  >{conv.last_message || "No messages"}</span
                >
                <!-- Date: visible by default, hidden on hover -->
                <span
                  class="whitespace-nowrap text-[11px] opacity-40 group-hover:opacity-0 transition-opacity"
                  >{formatTime(conv.updated_at)}</span
                >
              </div>
            {/if}
          </button>

          {#if !compact}
            <!-- Actions Menu (3 dots): hidden by default, visible on hover -->
            <div
              class="absolute right-1.5 bottom-1.5 opacity-0 group-hover:opacity-100 transition-opacity z-10"
            >
              <AppDropdown placement="bottom-end">
                {#snippet trigger()}
                  <button
                    class={`p-1 rounded transition-colors ${
                      isActive(conv.id)
                        ? "hover:bg-white/20"
                        : "hover:bg-gray-200 dark:hover:bg-gray-700"
                    }`}
                    onclick={(e) => e.stopPropagation()}
                    title="More actions"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke-width="1.5"
                      stroke="currentColor"
                      class={`w-5 h-5 ${
                        isActive(conv.id)
                          ? "text-white/80"
                          : "text-slate-500 dark:text-slate-400"
                      }`}
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z"
                      />
                    </svg>
                  </button>
                {/snippet}
                <AppDropdownItem
                  onclick={() => {
                    editingId = conv.id;
                    editTitle = conv.title;
                  }}
                >
                  <Icon icon="mdi:pencil" class="w-4 h-4" />
                  Rename
                </AppDropdownItem>
                <AppDropdownItem
                  onclick={() => {
                    deleteTargetId = conv.id;
                    isDeletingAll = false;
                    deleteModalOpen = true;
                  }}
                >
                  <span
                    class="flex items-center gap-2 text-red-600 dark:text-red-500"
                  >
                    <Icon icon="mdi:delete-outline" class="w-4 h-4" />
                    Delete
                  </span>
                </AppDropdownItem>
              </AppDropdown>
            </div>
          {/if}
          <!-- Compact tooltip is handled via title attribute on the button above -->
        {/if}
      </div>
    {/each}
  </div>

  <!-- Delete Confirmation Modal -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <dialog
    class="confirmation-modal"
    bind:this={deleteModal}
    onclose={() => (deleteModalOpen = false)}
    onclick={(e) => {
      if (e.target === deleteModal) deleteModalOpen = false;
    }}
  >
    <div class="modal-box bg-base-100 text-base-content">
      <h3 class="text-lg font-bold">Confirm Deletion</h3>
      <p class="py-4">
        Are you sure you want to {isDeletingAll
          ? "delete all conversations"
          : "delete this conversation"}? This action cannot be undone.
      </p>
      <div class="modal-action">
        <button
          class="btn"
          type="button"
          onclick={() => (deleteModalOpen = false)}>Cancel</button
        >
        <button class="btn btn-error" type="button" onclick={confirmDelete}
          >Delete</button
        >
      </div>
    </div>
  </dialog>
</div>

<style>
  /* Custom modal styling to avoid DaisyUI conflicts and ensure proper overlay */
  dialog.confirmation-modal {
    /* Reset native dialog styles */
    padding: 0;
    margin: 0;
    border: none;

    /* Full screen overlay positioning */
    position: fixed;
    inset: 0;
    width: 100vw;
    height: 100vh;
    max-width: none;
    max-height: none;

    /* Flex/Grid for centering */
    display: none; /* Default hidden */
    place-items: center;
    z-index: 9999;

    /* Visuals: Dark backdrop on the dialog container itself */
    background-color: rgba(0, 0, 0, 0.5);
    color: inherit;
  }

  dialog.confirmation-modal[open] {
    display: grid; /* Show when open */
  }

  /* Ensure the box has proper styling and full opacity */
  :global(dialog.confirmation-modal .modal-box) {
    padding: 1.5rem;
    border-radius: 1rem;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
    position: relative;
    width: min(90vw, 32rem);
    opacity: 1; /* Explicit opacity */
    isolation: isolate; /* Create new stacking context */
  }

  /* Disable native backdrop as we use the dialog itself */
  dialog.confirmation-modal::backdrop {
    background: transparent;
    display: none;
  }

  /* Custom Scrollbar - macOS/ChatGPT style */
  .conversation-list-scroll {
    /* Firefox */
    scrollbar-width: thin;
    scrollbar-color: rgba(156, 163, 175, 0.4) transparent;
    /* Ensure scrollbar doesn't take space in compact mode */
    overflow-y: overlay;
    overflow-y: auto; /* Fallback for browsers that don't support overlay */
  }

  @supports (overflow-y: overlay) {
    .conversation-list-scroll {
      overflow-y: overlay;
    }
  }

  .conversation-list-scroll::-webkit-scrollbar {
    width: 4px; /* Even thinner for compact mode */
  }
  .conversation-list-scroll::-webkit-scrollbar-track {
    background: transparent;
  }
  .conversation-list-scroll::-webkit-scrollbar-thumb {
    background-color: rgba(156, 163, 175, 0.3);
    border-radius: 20px;
  }
  .conversation-list-scroll:hover::-webkit-scrollbar-thumb {
    background-color: rgba(156, 163, 175, 0.6);
  }
  :global(.dark) .conversation-list-scroll::-webkit-scrollbar-thumb {
    background-color: rgba(107, 114, 128, 0.3);
  }
  :global(.dark) .conversation-list-scroll:hover::-webkit-scrollbar-thumb {
    background-color: rgba(107, 114, 128, 0.6);
  }

  /* active-conversation class removed — now handled with Tailwind (bg-primary/10 text-primary) */
</style>
