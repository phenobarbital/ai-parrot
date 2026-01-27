<script lang="ts">
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';

	let { dashboard, isOpen = $bindable(false) } = $props<{
		dashboard: Dashboard;
		isOpen: boolean;
	}>();

	let dialog: HTMLDialogElement;
	let activeTab = $state('general');

	$effect(() => {
		if (isOpen) dialog?.showModal();
		else dialog?.close();
	});

	function close() {
		isOpen = false;
	}

	function resetLayout() {
		// dashboard.resetLayout(); // Implement this in Dashboard class if needed or just clear widgets?
		// User req: "Reset returns widgets to the last SAVED snapshot... If no saved snapshot exists, reset to default"
		// For now, we simulate by reloading or clearing user changes since last save?
		// Or simply invoke a method on Dashboard to revert working copy.
		// Given our persistence model is instant-save, "Reset" might imply "Clear All" or "Revert to Factory".
		// Let's implement a 'clear' for now or simple toast.
		alert('Reset layout not fully implemented yet');
	}

	async function saveContext() {
		await dashboard.save();
		close();
	}
</script>

<dialog class="modal" bind:this={dialog} onclose={close}>
	<div class="modal-box flex h-[60vh] w-11/12 max-w-2xl flex-col overflow-hidden p-0">
		<!-- Header -->
		<div class="bg-base-100 flex items-center justify-between border-b p-4">
			<h3 class="text-lg font-bold">Dashboard Settings</h3>
			<button class="btn btn-sm btn-ghost btn-circle" onclick={close}>✕</button>
		</div>

		<!-- Content -->
		<div class="flex flex-1 flex-col overflow-hidden">
			<!-- Tabs -->
			<div class="tabs tabs-bordered px-4 pt-2">
				<button
					class="tab"
					class:tab-active={activeTab === 'general'}
					onclick={() => (activeTab = 'general')}>General</button
				>
				<button
					class="tab"
					class:tab-active={activeTab === 'layout'}
					onclick={() => (activeTab = 'layout')}>Layout</button
				>
			</div>

			<div class="bg-base-200/50 flex-1 overflow-y-auto p-6">
				{#if activeTab === 'general'}
					<div class="form-control w-full">
						<label class="label">
							<span class="label-text">Dashboard Title</span>
						</label>
						<input type="text" bind:value={dashboard.title} class="input input-bordered w-full" />
					</div>
				{:else if activeTab === 'layout'}
					<div class="alert bg-base-100 mb-4 shadow-sm">
						<div>
							<div class="font-bold">Current Layout: {dashboard.layoutMode}</div>
							<div class="text-xs">Widget positions are saved per layout mode.</div>
						</div>
					</div>

					<div class="flex gap-2">
						<button class="btn btn-primary btn-sm gap-2" onclick={() => dashboard.save()}>
							💾 Save Current Layout
						</button>
						<button class="btn btn-outline btn-sm gap-2" onclick={resetLayout}>
							🔄 Reset to Default
						</button>
					</div>
				{/if}
			</div>
		</div>

		<!-- Footer -->
		<div class="modal-action bg-base-100 m-0 border-t p-4">
			<button class="btn" onclick={close}>Close</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>close</button>
	</form>
</dialog>
