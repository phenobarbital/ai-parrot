<script lang="ts">
	import { crew as crewApi } from '$lib/api/crew';
	// Removed markdownToHtml for now to simplify dependencies, or can assume it's available or use plain text
	// import { markdownToHtml } from '$lib/utils/markdown';

	let { showModal = false, crew = null, onClose = () => {} } = $props();

	// Simplified Execution Modal for Migration
	let question = $state('');
	let isSubmitting = $state(false);
	let jobStatus = $state<any>(null);
	let jobError = $state('');

	// Derived
	// @ts-ignore
	let crewName = $derived(crew?.name || 'Unknown Crew');

	async function handleSubmit(event: Event) {
		event.preventDefault();
		if (!question.trim()) return;

		isSubmitting = true;
		jobError = '';
		jobStatus = null;

		try {
			// @ts-ignore
			const execution = await crewApi.executeCrew(crew.crew_id, question, {
				// @ts-ignore
				execution_mode: crew.execution_mode || 'sequential',
				user_id: 'default-user', // TODO: Get from auth
				session_id: crypto.randomUUID()
			});
			jobStatus = execution;
			// Start polling
			pollJob(execution.job_id);
		} catch (error: any) {
			console.error(error);
			jobError = error.message || 'Execution failed';
			isSubmitting = false;
		}
	}

	async function pollJob(jobId: string) {
		try {
			const result = await crewApi.pollJobUntilComplete(jobId);
			jobStatus = result;
		} catch (e) {
			jobError = 'Polling timed out or failed';
		} finally {
			isSubmitting = false;
		}
	}

	function handleClose() {
		if (!isSubmitting) onClose();
	}
</script>

{#if showModal}
	<div class="fixed inset-0 z-50 overflow-y-auto bg-black/50 backdrop-blur-sm">
		<div class="flex min-h-screen items-center justify-center p-4">
			<div class="w-full max-w-2xl rounded-xl bg-white shadow-2xl dark:bg-gray-800">
				<!-- Header -->
				<div
					class="flex items-center justify-between border-b border-gray-100 p-6 dark:border-gray-700"
				>
					<h2 class="text-xl font-bold text-gray-900 dark:text-white">Ask {crewName}</h2>
					<button onclick={handleClose} class="text-gray-400 hover:text-gray-500">
						<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
				<div class="p-6">
					{#if !jobStatus}
						<form onsubmit={handleSubmit}>
							<label
								class="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300"
								for="question"
							>
								What task would you like the crew to perform?
							</label>
							<textarea
								id="question"
								rows="4"
								class="w-full rounded-lg border border-gray-300 bg-gray-50 p-3 text-gray-900 focus:border-blue-500 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
								placeholder="Describe your task in detail..."
								bind:value={question}
								disabled={isSubmitting}
							></textarea>

							{#if jobError}
								<div
									class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-600 dark:bg-red-900/30 dark:text-red-400"
								>
									{jobError}
								</div>
							{/if}

							<div class="mt-6 flex justify-end">
								<button
									type="button"
									onclick={handleClose}
									class="mr-3 rounded-lg px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
									disabled={isSubmitting}
								>
									Cancel
								</button>
								<button
									type="submit"
									class="rounded-lg bg-blue-700 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-800 focus:outline-none focus:ring-4 focus:ring-blue-300 disabled:opacity-50 dark:bg-blue-600 dark:hover:bg-blue-700"
									disabled={isSubmitting || !question.trim()}
								>
									{isSubmitting ? 'Starting...' : 'Execute Crew'}
								</button>
							</div>
						</form>
					{:else}
						<!-- Execution Status View -->
						<div class="space-y-4">
							<div class="flex items-center gap-3">
								{#if jobStatus.status === 'running' || jobStatus.status === 'pending'}
									<span class="loading loading-spinner text-blue-600"></span>
									<span class="font-medium text-blue-600">Running...</span>
								{:else if jobStatus.status === 'completed'}
									<span class="font-bold text-green-600">✓ Completed</span>
								{:else}
									<span class="font-bold text-red-600">Failed</span>
								{/if}
							</div>

							<div
								class="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900"
							>
								<h3 class="mb-2 text-sm font-bold uppercase text-gray-500">Result</h3>
								<div class="prose prose-sm dark:prose-invert max-w-none">
									{jobStatus.result || jobStatus.output || 'No output available.'}
								</div>
							</div>

							<div class="mt-6 flex justify-end">
								<button
									onclick={() => {
										jobStatus = null;
									}}
									class="rounded-lg bg-gray-200 px-5 py-2.5 text-sm font-medium text-gray-800 hover:bg-gray-300 dark:bg-gray-700 dark:text-white"
								>
									New Task
								</button>
							</div>
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}
