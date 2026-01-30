<script lang="ts">
	import { onMount } from 'svelte';
	import { ChatService } from '$lib/services/chat-db';
	import type { AgentConversation } from '$lib/types/agent';
	import { liveQuery } from 'dexie';

	let { agentName, currentSessionId, onSelect, onNew } = $props<{
		agentName: string;
		currentSessionId: string | null;
		onSelect: (id: string) => void;
		onNew: () => void;
	}>();

	// Live query for conversations
	let conversations = $state<AgentConversation[]>([]);

	$effect(() => {
		const sub = liveQuery(() => ChatService.getConversations(agentName)).subscribe((value) => {
			conversations = value;
		});
		return () => sub.unsubscribe();
	});

	function formatTime(date: Date) {
		return new Date(date).toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}
	// Delete modal state
	let deleteModalOpen = $state(false);
	let deleteTargetId = $state<string | null>(null);
	let isDeletingAll = $state(false);
	let deleteModal: HTMLDialogElement;

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
			await ChatService.clearHistory();
			onNew(); // Reset to new conversation if clearing all
		} else if (deleteTargetId) {
			await ChatService.deleteConversation(deleteTargetId);
			if (currentSessionId === deleteTargetId) {
				onNew(); // Reset if deleting active conversation
			}
		}
		deleteModalOpen = false;
		deleteTargetId = null;
		isDeletingAll = false;
	}
</script>

<div class="bg-base-200 border-base-300 flex h-full w-80 flex-col border-r">
	<div class="border-base-300 border-b p-4">
		<button class="btn btn-primary w-full gap-2" onclick={onNew}>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke-width="1.5"
				stroke="currentColor"
				class="h-5 w-5"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
			</svg>
			New Conversation
		</button>
	</div>

	<div class="flex-1 space-y-1 overflow-y-auto p-2">
		{#if conversations.length === 0}
			<div class="p-4 text-center text-sm opacity-50">No conversations yet</div>
		{/if}

		{#each conversations as conv (conv.id)}
			<div class="group relative">
				<button
					class={`hover:bg-base-300 flex w-full flex-col gap-1 rounded-lg p-3 text-left transition-colors ${currentSessionId === conv.id ? 'bg-base-300 border-primary border-l-4' : ''}`}
					onclick={() => onSelect(conv.id)}
				>
					<span class="block w-full truncate text-sm font-medium">{conv.title}</span>
					<div class="flex w-full items-center justify-between">
						<span class="max-w-[150px] truncate text-xs opacity-50"
							>{conv.last_message || 'No messages'}</span
						>
						<span class="whitespace-nowrap text-[10px] opacity-40"
							>{formatTime(conv.updated_at)}</span
						>
					</div>
				</button>
				<button
					class="btn btn-ghost btn-xs btn-square absolute right-2 top-2 opacity-0 transition-opacity group-hover:opacity-100"
					onclick={(e) => promptDelete(conv.id, e)}
					title="Delete Conversation"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="text-error h-4 w-4"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
						/>
					</svg>
				</button>
			</div>
		{/each}
	</div>

	<!-- Cleanup Button -->
	{#if conversations.length > 0}
		<div class="border-base-300 border-t p-4">
			<button class="btn btn-outline btn-error btn-sm w-full gap-2" onclick={promptDeleteAll}>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="h-4 w-4"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
					/>
				</svg>
				Cleanup Conversations
			</button>
		</div>
	{/if}

	<!-- Delete Confirmation Modal -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<dialog 
		class="confirmation-modal" 
		bind:this={deleteModal} 
		onclose={() => (deleteModalOpen = false)}
		onclick={(e) => { if (e.target === deleteModal) deleteModalOpen = false; }}
	>
		<div class="modal-box bg-base-100 text-base-content">
			<h3 class="text-lg font-bold">Confirm Deletion</h3>
			<p class="py-4">
				Are you sure you want to {isDeletingAll
					? 'delete all conversations'
					: 'delete this conversation'}? This action cannot be undone.
			</p>
			<div class="modal-action">
				<button class="btn" type="button" onclick={() => (deleteModalOpen = false)}>Cancel</button>
				<button class="btn btn-error" type="button" onclick={confirmDelete}>Delete</button>
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
</style>
