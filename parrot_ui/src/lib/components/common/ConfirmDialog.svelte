<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	let {
		isOpen = false,
		title = 'Confirm Action',
		message = 'Are you sure you want to proceed?',
		confirmText = 'Confirm',
		cancelText = 'Cancel',
		confirmButtonClass = '',
		isDangerous = false,
		onconfirm = () => {},
		oncancel = () => {}
	} = $props();

	const dispatch = createEventDispatcher();

	function handleConfirm() {
		dispatch('confirm');
		onconfirm();
	}

	function handleCancel() {
		dispatch('cancel');
		oncancel();
	}

	// Close on Escape key
	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			handleCancel();
		}
	}
</script>

{#if isOpen}
	<div
		class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 p-4"
		onclick={handleCancel}
		role="button"
		tabindex="0"
		onkeydown={handleKeydown}
	>
		<div
			class="w-full max-w-md rounded-xl bg-white shadow-xl dark:bg-gray-800"
			onclick={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			tabindex="-1"
			onkeydown={handleKeydown}
		>
			<!-- Header -->
			<div
				class="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700"
			>
				<h2 id="dialog-title" class="text-lg font-semibold text-gray-900 dark:text-white">
					{title}
				</h2>
				<button
					onclick={handleCancel}
					class="text-gray-400 transition-colors hover:text-gray-500 dark:hover:text-gray-300"
					aria-label="Close dialog"
				>
					<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M6 18L18 6M6 6l12 12"
						/>
					</svg>
				</button>
			</div>

			<!-- Body -->
			<div class="px-4 py-4">
				<p class="text-sm text-gray-600 dark:text-gray-300">
					{message}
				</p>
			</div>

			<!-- Footer -->
			<div class="flex gap-2 border-t border-gray-200 px-4 py-3 dark:border-gray-700">
				<button
					onclick={handleCancel}
					class="flex-1 rounded border border-gray-300 px-3 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
				>
					{cancelText}
				</button>
				<button
					onclick={handleConfirm}
					class="flex-1 rounded px-3 py-2 text-sm text-white transition-colors {confirmButtonClass ||
						(isDangerous ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700')}"
				>
					{confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Ensure dialog is always on top */
	:global(.confirm-dialog-wrapper) {
		z-index: 9999;
	}
</style>
