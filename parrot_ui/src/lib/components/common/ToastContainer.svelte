<script lang="ts">
	import { notificationStore } from '$lib/stores/notifications.svelte';
	import { flip } from 'svelte/animate';
	import { fade, fly } from 'svelte/transition';

	let activeToasts = $state<any[]>([]);

	$effect(() => {
		// Watch for new notifications that are toast=true AND shown!=true
        // We only check the most recent few to avoid scanning the whole history excessively,
        // but typically the new one is at the top [0].
		const latestInfo = notificationStore.notifications[0];
		if (latestInfo && latestInfo.toast && !latestInfo.shown) {
            // Mark as shown immediately in store to prevent re-toast on remount
            notificationStore.markAsShown(latestInfo.id);
			addToToastQueue(latestInfo);
		}
	});

	function addToToastQueue(notification: any) {
		activeToasts = [...activeToasts, notification];
		setTimeout(() => {
			removeToast(notification.id);
		}, notification.duration || 4000);
	}

	function removeToast(id: string) {
		activeToasts = activeToasts.filter((t) => t.id !== id);
	}

	function getAccentColor(type: string) {
		switch (type) {
			case 'success': return 'bg-emerald-500';
			case 'error': return 'bg-rose-500';
			case 'warning': return 'bg-amber-500';
			default: return 'bg-sky-500';
		}
	}

	function getIconBg(type: string) {
		switch (type) {
			case 'success': return 'bg-emerald-500';
			case 'error': return 'bg-rose-500';
			case 'warning': return 'bg-amber-500';
			default: return 'bg-sky-500';
		}
	}
</script>

{#if activeToasts.length > 0}
	<div class="fixed top-16 right-4 z-[9999] flex flex-col gap-3 pointer-events-none">
		{#each activeToasts as toast (toast.id)}
			<div
				class="pointer-events-auto flex w-80 overflow-hidden rounded-lg bg-base-100 shadow-lg ring-1 ring-base-300 transition-all duration-300"
				animate:flip={{ duration: 300 }}
				in:fly={{ x: 50, duration: 300, opacity: 0 }}
				out:fade={{ duration: 200 }}
			>
                <!-- Color Strip -->
                <div class:bg-info={toast.type === 'info'}
                     class:bg-success={toast.type === 'success'}
                     class:bg-warning={toast.type === 'warning'}
                     class:bg-error={toast.type === 'error'}
                     class="w-1.5 shrink-0"
                ></div>

				<div class="flex flex-1 gap-3 p-4">
					<div class="shrink-0 pt-0.5">
						{#if toast.type === 'success'}
							<div class="h-8 w-8 rounded-full bg-success/10 flex items-center justify-center text-success">
                                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
						{:else if toast.type === 'error'}
							<div class="h-8 w-8 rounded-full bg-error/10 flex items-center justify-center text-error">
                                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </div>
						{:else if toast.type === 'warning'}
							<div class="h-8 w-8 rounded-full bg-warning/10 flex items-center justify-center text-warning">
                                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                                </svg>
                            </div>
						{:else}
							<div class="h-8 w-8 rounded-full bg-info/10 flex items-center justify-center text-info">
                                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                            </div>
						{/if}
					</div>
					
					<div class="flex-1 min-w-0 py-0.5">
						<h3 class="font-semibold text-sm text-base-content leading-none mb-1">{toast.title}</h3>
						<p class="text-xs text-base-content/70 leading-relaxed break-words">
							{toast.message}
						</p>
					</div>

					<button 
						class="shrink-0 -mr-1 -mt-1 h-6 w-6 rounded-full flex items-center justify-center text-base-content/40 hover:bg-base-200 hover:text-base-content transition-colors"
						onclick={() => removeToast(toast.id)}
					>
                        <span class="sr-only">Close</span>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
					</button>
				</div>
			</div>
		{/each}
	</div>
{/if}
