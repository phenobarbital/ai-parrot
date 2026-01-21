<script lang="ts">
	import { crew as crewApi } from '$lib/api/crew';
	import { crewStore } from '$lib/stores/crewStore';
	import { addToast } from '$lib/stores/toast';

	let { handleAddAgent, handleExport, handleClose, viewMode = false } = $props();

	let crewDescription = $state('');
	let crewExecutionMode = $state('sequential');

	// Local state for toast notifications (visual only)
	let uploadStatus = $state<{ type: 'success' | 'error'; message: string } | null>(null);
	let toastTimeout: any;
	let uploading = $state(false);

	// Sync from store
	$effect(() => {
		let crew = $crewStore.metadata;
		crewDescription = crew.description || '';
		crewExecutionMode = crew.execution_mode || 'sequential';
	});

	function updateMetadata() {
		crewStore.updateMetadata({
			description: crewDescription,
			execution_mode: crewExecutionMode
		});
	}

	function showToast(type: 'success' | 'error', message: string) {
		// Also use the global toast store
		addToast(message, type, 5000);

		// Keep local toast for this component specific feedback loop if needed,
		// or just rely on global toast. For refined UX, we might keep the local banner too if it's styled nicely within the toolbar.
		// The original code had a local banner. Let's keep it but also push global.
		uploadStatus = { type, message };

		if (toastTimeout) clearTimeout(toastTimeout);
		toastTimeout = setTimeout(() => {
			uploadStatus = null;
		}, 5000);
	}

	function dismissToast() {
		if (toastTimeout) {
			clearTimeout(toastTimeout);
		}
		uploadStatus = null;
	}

	async function uploadToAPI() {
		try {
			uploading = true;
			const crewJSON = crewStore.exportToJSON();
			// @ts-ignore
			const response = await crewApi.createCrew(crewJSON);
			showToast('success', `Crew "${response.name ?? crewJSON.name}" created successfully!`);
		} catch (error: any) {
			const responseMessage =
				error?.response?.data?.message || error?.message || 'Failed to upload crew';
			showToast('error', responseMessage);
		} finally {
			uploading = false;
		}
	}
</script>

<div class="border-b border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
	<!-- Header Title Bar -->
	<div
		class="flex items-center justify-between border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white px-6 py-3 dark:border-gray-700 dark:from-gray-800 dark:to-gray-800"
	>
		<div class="flex items-center gap-3">
			<div
				class="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-100 text-2xl shadow-sm dark:bg-violet-900/30"
			>
				🦜
			</div>
			<div>
				<h1 class="text-lg font-bold text-gray-900 dark:text-white">AgentCrew Builder</h1>
				<p class="text-xs text-gray-500 dark:text-gray-400">Design your AI agent workflow</p>
			</div>
		</div>

		<div class="flex items-center gap-2">
			{#if !viewMode}
				<button
					class="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:bg-blue-700 hover:shadow-md"
					onclick={uploadToAPI}
					disabled={uploading}
				>
					{#if uploading}
						<svg class="h-4 w-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
							<circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="4"
							></circle>
							<path
								class="opacity-75"
								fill="currentColor"
								d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
							></path>
						</svg>
						Saving...
					{:else}
						<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
							/>
						</svg>
						Upload
					{/if}
				</button>
			{/if}

			<button
				onclick={handleAddAgent}
				class="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 hover:text-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
				disabled={viewMode}
			>
				<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 4v16m8-8H4"
					/>
				</svg>
				Add Agent
			</button>

			<button
				onclick={handleExport}
				class="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 hover:text-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
			>
				<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
					/>
				</svg>
				Export JSON
			</button>

			<!-- Close Button -->
			{#if handleClose}
				<div class="ml-2 border-l border-gray-300 pl-2 dark:border-gray-600">
					<button
						onclick={handleClose}
						class="flex items-center justify-center rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
						title="Close Builder"
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
			{/if}
		</div>
	</div>

	<!-- Configuration Bar -->
	<div class="flex items-center gap-4 px-6 py-3">
		<div class="flex flex-1 items-center gap-4">
			<div class="w-64">
				<label class="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
					>Crew Name</label
				>
				<input
					class="w-full rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 shadow-sm transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:focus:border-blue-400 dark:focus:ring-blue-400"
					type="text"
					bind:value={$crewStore.metadata.name}
					onchange={updateMetadata}
					placeholder="Enter crew name..."
					disabled={viewMode}
					readonly={viewMode}
				/>
			</div>

			<div class="flex-1">
				<label class="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
					>Description</label
				>
				<input
					class="w-full rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 shadow-sm transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:focus:border-blue-400 dark:focus:ring-blue-400"
					type="text"
					bind:value={crewDescription}
					onchange={updateMetadata}
					placeholder="Enter description..."
					disabled={viewMode}
					readonly={viewMode}
				/>
			</div>

			<div class="w-56">
				<label class="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
					>Execution Mode</label
				>
				<select
					class="w-full rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 shadow-sm transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:focus:border-blue-400 dark:focus:ring-blue-400"
					bind:value={crewExecutionMode}
					onchange={updateMetadata}
					disabled={viewMode}
				>
					<option value="sequential">Sequential</option>
					<option value="parallel">Parallel</option>
					<option value="hierarchical">Hierarchical</option>
				</select>
			</div>
		</div>
	</div>
</div>

{#if uploadStatus}
	<div
		class={`animate-in fade-in slide-in-from-right-5 fixed right-4 top-24 z-50 max-w-sm rounded-lg border p-4 shadow-lg ${uploadStatus.type === 'success' ? 'border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-900 dark:text-green-200' : 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-900 dark:text-red-200'}`}
	>
		<div class="flex items-start gap-3">
			<div class="flex-shrink-0">
				{#if uploadStatus.type === 'success'}
					<svg
						class="h-5 w-5 text-green-600 dark:text-green-400"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M5 13l4 4L19 7"
						/>
					</svg>
				{:else}
					<svg
						class="h-5 w-5 text-red-600 dark:text-red-400"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M6 18L18 6M6 6l12 12"
						/>
					</svg>
				{/if}
			</div>
			<div class="flex-1">
				<p class="text-sm font-medium">
					{uploadStatus.message}
				</p>
			</div>
			<button
				type="button"
				onclick={dismissToast}
				class="ml-4 inline-flex flex-shrink-0 rounded-md p-1.5 opacity-60 hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-offset-2"
			>
				<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M6 18L18 6M6 6l12 12"
					/>
				</svg>
			</button>
		</div>
	</div>
{/if}
