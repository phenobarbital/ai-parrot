<script lang="ts">
	import { notificationStore } from '$lib/stores/notifications.svelte';
	import { flip } from 'svelte/animate';
	import { fade, fly } from 'svelte/transition';

	let activeToasts = $state<any[]>([]);

	const processedIds = new Set<string>();

	$effect(() => {
		const latestInfo = notificationStore.notifications[0];
		if (latestInfo && latestInfo.toast && !processedIds.has(latestInfo.id)) {
			processedIds.add(latestInfo.id);
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
	<div class="fixed bottom-6 right-6 z-[9999] flex flex-col gap-3">
		{#each activeToasts as toast (toast.id)}
			<div
				class="relative flex w-80 items-center gap-3 overflow-hidden rounded-lg bg-[#1e293b] pl-4 pr-3 py-3"
				role="alert"
				animate:flip={{ duration: 300 }}
				in:fly={{ x: 100, duration: 300 }}
				out:fade={{ duration: 200 }}
			>
				<!-- Left accent border -->
				<div class="absolute left-0 top-0 h-full w-1 rounded-l-lg {getAccentColor(toast.type)}"></div>

				<!-- Icon -->
				{#if toast.type === 'success'}
					<div class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full {getIconBg(toast.type)}">
						<svg class="h-2.5 w-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
							<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
						</svg>
					</div>
				{:else if toast.type === 'error'}
					<div class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full {getIconBg(toast.type)}">
						<svg class="h-2.5 w-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
							<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</div>
				{:else if toast.type === 'warning'}
					<div class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full {getIconBg(toast.type)}">
						<svg class="h-2.5 w-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
							<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01" />
						</svg>
					</div>
				{:else}
					<div class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full {getIconBg(toast.type)}">
						<svg class="h-2.5 w-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
							<path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01" />
						</svg>
					</div>
				{/if}

				<!-- Content -->
				<div class="flex-1 min-w-0">
					<h3 class="text-sm font-semibold text-white">{toast.title || (toast.type === 'error' ? 'Error' : toast.type === 'success' ? 'Success' : 'Info')}</h3>
					<p class="text-xs text-slate-400">{toast.message}</p>
				</div>

				<!-- Close button -->
				<button 
					class="flex items-center justify-center text-slate-500 hover:text-slate-300 transition-colors"
					onclick={() => removeToast(toast.id)}
					aria-label="Cerrar"
				>
					<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
		{/each}
	</div>
{/if}
