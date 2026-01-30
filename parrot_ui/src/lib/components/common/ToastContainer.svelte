<script lang="ts">
	import { notificationStore } from '$lib/stores/notifications.svelte';
	import { flip } from 'svelte/animate';
	import { fade, fly } from 'svelte/transition';

	// Filter only toast notifications that are not read (or manage visibility separately)
	// Actually the store keeps history. We should probably only show "active" toasts.
	// implementing a derived view or just filtering in template.
	// For simplicity, let's assume we show the last 5 notifications if they are 'toast' and recent.
	// Better yet, let's just use the store and filter for 'toast' property and maybe a 'visible' state if we had it.
	// But since the store is simple, let's just show notifications that have `toast: true` and are recent.
	// The store doesn't auto-remove them from the list, it just slices to 50.
	// So we need a local mechanism or a way to dismiss them from view but keep in history.

	// Let's refine the strategy: Visual Toasts should be ephemeral.
	// The `notificationStore` logic I wrote earlier doesn't auto-remove from the *array* except for capacity.
	// I need a way to track which ones are currently "showing" as toasts.
	// I'll add a local state here to track shown toasts.

	let activeToasts = $state<any[]>([]);

	const processedIds = new Set<string>();

	$effect(() => {
		// Watch for new notifications
		const latestInfo = notificationStore.notifications[0];
		if (latestInfo && latestInfo.toast && !processedIds.has(latestInfo.id)) {
			processedIds.add(latestInfo.id);
			addToToastQueue(latestInfo);
		}
	});

	function addToToastQueue(notification: any) {
		activeToasts = [...activeToasts, notification];

		// Auto dismiss
		setTimeout(() => {
			removeToast(notification.id);
		}, notification.duration || 3000);
	}

	function removeToast(id: string) {
		activeToasts = activeToasts.filter((t) => t.id !== id);
	}
</script>

{#if activeToasts.length > 0}
	<div class="toast toast-end toast-bottom z-50 flex flex-col gap-2 p-4">
		{#each activeToasts as toast (toast.id)}
			<div
				class="alert w-full max-w-sm shadow-lg transition-all duration-300"
				class:alert-info={toast.type === 'info'}
				class:alert-success={toast.type === 'success'}
				class:alert-warning={toast.type === 'warning'}
				class:alert-error={toast.type === 'error'}
				animate:flip={{ duration: 300 }}
				in:fly={{ y: 20, duration: 300 }}
				out:fade={{ duration: 200 }}
			>
				{#if toast.type === 'success'}
					<svg class="h-6 w-6 shrink-0 stroke-current" fill="none" viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
						/></svg
					>
				{:else if toast.type === 'error'}
					<svg class="h-6 w-6 shrink-0 stroke-current" fill="none" viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
						/></svg
					>
				{:else if toast.type === 'warning'}
					<svg class="h-6 w-6 shrink-0 stroke-current" fill="none" viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
						/></svg
					>
				{:else}
					<svg class="h-6 w-6 shrink-0 stroke-current" fill="none" viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						/></svg
					>
				{/if}
				<div>
					<h3 class="text-sm font-bold">{toast.title}</h3>
					<div class="text-xs">{toast.message}</div>
				</div>
				<button class="btn btn-ghost btn-xs btn-circle" onclick={() => removeToast(toast.id)}>
					✕
				</button>
			</div>
		{/each}
	</div>
{/if}
