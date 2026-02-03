<script lang="ts">
	import { browser } from '$app/environment';
	import BuilderModal from './BuilderModal.svelte';
	import CrewExecutionWizard from './CrewExecutionWizard.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { crew as crewApi } from '$lib/api/crew';
	import { crewStore } from '$lib/stores/crewStore';
	import { addToast } from '$lib/stores/toast';

	let { moduleData } = $props();

	let crews = $state<any[]>([]);
	let crewsLoading = $state(false);
	let crewsError = $state('');
	let totalCrews = $state(0);
	let showBuilderModal = $state(false);
	let selectedCrewId = $state<string | null>(null);
	let viewMode = $state(false);
	let importInProgress = $state(false);
	let showDeleteDialog = $state(false);
	let crewToDelete = $state<any>(null);
	let showAskModal = $state(false);
	let crewToAsk = $state(null);
	let activeJobs = $state<any[]>([]);
	let completedJobs = $state<any[]>([]);
	let selectedJobId = $state<string | null>(null);
	let selectedJobStatus = $state<string | null>(null);

	// Stats computed from crews data
	let stats = $derived({
		totalCrews: totalCrews,
		executions: completedJobs.length, // Update stat
		successRate: 100,
		avgDuration: 0
	});

	async function fetchCrews() {
		if (!browser) return;

		crewsLoading = true;
		crewsError = '';

		try {
			// Fetch crews, active jobs, and completed jobs
			// Note: We need to implement listCompletedJobs in API and Backend
			const [crewsRes, jobsRes, completedRes] = await Promise.all([
				crewApi.listCrews(),
				crewApi.listActiveJobs(),
				crewApi.listCompletedJobs()
			]);
			
			crews = Array.isArray(crewsRes?.crews) ? crewsRes.crews : [];
			totalCrews = typeof crewsRes?.total === 'number' ? crewsRes.total : crews.length;
			
			activeJobs = Array.isArray(jobsRes) ? jobsRes : [];
			completedJobs = Array.isArray(completedRes) ? completedRes : [];
			
		} catch (error: any) {
			console.error('Failed to load data', error);
			crewsError = error instanceof Error ? error.message : 'Unable to load crews at this time.';
			crews = [];
			totalCrews = 0;
			activeJobs = [];
			completedJobs = [];
		} finally {
			crewsLoading = false;
		}
	}

	function handleResumeJob(job: any) {
		// Construct partial crew object for wizard
		crewToAsk = {
			crew_id: job.crew_id,
			name: job.crew_name,
			execution_mode: job.execution_mode
		};
		selectedJobId = job.job_id;
		selectedJobStatus = job.status;
		showAskModal = true;
	}

	$effect(() => {
		if (!browser) return;
		fetchCrews();
	});

	function handleStartBuilding() {
		selectedCrewId = null;
		viewMode = false;
		showBuilderModal = true;
	}

	function handleImportJSON() {
		if (!browser || importInProgress) return;

		const input = document.createElement('input');
		input.type = 'file';
		input.accept = 'application/json,.json';
		input.onchange = async (event) => {
			// @ts-ignore
			const file = event?.target?.files?.[0];
			if (!file) return;

			importInProgress = true;
			crewsError = '';

			try {
				const fileContents = await file.text();
				const parsed = JSON.parse(fileContents);

				if (!parsed || typeof parsed !== 'object') {
					throw new Error('Invalid JSON configuration.');
				}

				crewStore.importCrew(parsed); // normalize
				const payload = crewStore.exportToJSON();

				// @ts-ignore
				const response = await crewApi.createCrew(payload);
				const crewName = response?.name ?? payload?.name ?? file.name;

				addToast(`Crew "${crewName}" imported successfully`, 'success');
				await fetchCrews();
			} catch (error: any) {
				console.error('Failed to import crew JSON', error);
				const message =
					error?.response?.data?.message || error?.message || 'Failed to import JSON file.';
				addToast(message, 'error');
			} finally {
				importInProgress = false;
				input.value = '';
				crewStore.reset();
			}
		};

		input.click();
	}

	function handleCloseBuilder() {
		showBuilderModal = false;
		selectedCrewId = null;
		viewMode = false;
		fetchCrews();
	}

	function handleViewCrew(crewId: string) {
		selectedCrewId = crewId;
		viewMode = true;
		showBuilderModal = true;
	}

	function formatDate(dateString: string) {
		if (!dateString) return '—';

		const date = new Date(dateString);
		if (Number.isNaN(date.getTime())) return dateString;

		return date.toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function handleDeleteClick(crew: any) {
		crewToDelete = crew;
		showDeleteDialog = true;
	}

	function handleCancelDelete() {
		showDeleteDialog = false;
		crewToDelete = null;
	}

	async function handleConfirmDelete() {
		if (!crewToDelete) return;

		try {
			await crewApi.deleteCrew(crewToDelete.crew_id);
			await fetchCrews();
		} catch (error: any) {
			console.error('Failed to delete crew', error);
			addToast(
				error?.response?.data?.message || error?.message || 'Failed to delete crew',
				'error'
			);
		} finally {
			showDeleteDialog = false;
			crewToDelete = null;
		}
	}

	function handleAskCrew(crew: any) {
		crewToAsk = crew;
		showAskModal = true;
	}

	function handleCloseAskModal() {
		showAskModal = false;
		crewToAsk = null;
	}

	// @ts-ignore
	const EXECUTION_MODE_GRADIENTS: Record<string, string> = {
		sequential: 'from-emerald-500 to-teal-500',
		parallel: 'from-sky-500 to-indigo-500',
		event: 'from-amber-500 to-orange-500',
		default: 'from-slate-500 to-slate-700'
	};

	function getExecutionModeClass(mode = '') {
		const key = mode.toLowerCase();
		const gradient = EXECUTION_MODE_GRADIENTS[key] ?? EXECUTION_MODE_GRADIENTS.default;
		return `inline-flex items-center gap-2 rounded-full bg-gradient-to-r ${gradient} px-3 py-1 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-slate-900/10 dark:shadow-black/40`;
	}

	function getExecutionModeLabel(mode = '') {
		if (!mode) return '—';
		return mode.replace(/_/g, ' ');
	}
</script>

{#if showBuilderModal}
	<BuilderModal
		showModal={showBuilderModal}
		crewId={selectedCrewId}
		{viewMode}
		onClose={handleCloseBuilder}
	/>
{:else}
	<div class="space-y-8 p-2">
		<!-- Action Cards -->
		<div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
			<!-- Create New Crew Card -->
			<div
				class="group rounded-2xl border border-slate-200/70 bg-white/90 p-6 shadow-lg shadow-slate-200/60 transition duration-200 hover:-translate-y-0.5 hover:shadow-2xl dark:border-slate-700 dark:bg-slate-900/80 dark:shadow-black/30"
			>
				<div class="mb-3 flex items-start gap-3">
					<div
						class="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-cyan-500 text-white shadow-lg shadow-blue-500/40"
					>
						<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M12 6v6m0 0v6m0-6h6m-6 0H6"
							/>
						</svg>
					</div>
					<div class="flex-1">
						<h3 class="mb-1 text-lg font-semibold text-gray-900 dark:text-white">
							Create New Crew
						</h3>
						<p class="text-sm text-gray-600 dark:text-gray-400">
							Design a new agent crew using our visual workflow builder.
						</p>
					</div>
				</div>
				<div class="flex justify-end">
					<button
						onclick={handleStartBuilding}
						class="cursor-pointer rounded-xl bg-gradient-to-r from-blue-600 to-emerald-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-blue-500/30 transition hover:shadow-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
					>
						Start Building
					</button>
				</div>
			</div>

			<!-- Import Crew Card -->
			<div
				class="group rounded-2xl border border-slate-200/70 bg-white/90 p-6 shadow-lg shadow-slate-200/60 transition duration-200 hover:-translate-y-0.5 hover:shadow-2xl dark:border-slate-700 dark:bg-slate-900/80 dark:shadow-black/30"
			>
				<div class="mb-3 flex items-start gap-3">
					<div
						class="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-500 text-white shadow-lg shadow-emerald-400/40"
					>
						<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
							/>
						</svg>
					</div>
					<div class="flex-1">
						<h3 class="mb-1 text-lg font-semibold text-gray-900 dark:text-white">Import Crew</h3>
						<p class="text-sm text-gray-600 dark:text-gray-400">
							Import an existing crew configuration from a JSON file.
						</p>
					</div>
				</div>
				<div class="flex justify-end">
					<button
						onclick={handleImportJSON}
						disabled={importInProgress}
						class="cursor-pointer rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 transition-colors hover:border-emerald-300 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100 dark:hover:border-emerald-400/60 dark:hover:bg-emerald-500/20"
					>
						{importInProgress ? 'Importing...' : 'Import JSON'}
					</button>
				</div>
			</div>
		</div>

		<!-- Active Jobs Section -->
		{#if activeJobs.length > 0}
		<div class="mt-8">
			<h3 class="mb-4 text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
				<span class="relative flex h-3 w-3">
				  <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
				  <span class="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
				</span>
				Active Jobs
			</h3>
			<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
				{#each activeJobs as job}
					<div class="flex items-center justify-between rounded-xl border border-green-200 bg-green-50/50 p-4 dark:border-green-900/30 dark:bg-green-900/10 transition hover:shadow-md">
						<div class="flex-1 min-w-0 mr-4">
							<div class="flex items-center gap-2 mb-1">
								<h4 class="font-medium text-gray-900 dark:text-white truncate">{job.crew_name}</h4>
								<span class="text-[10px] font-mono uppercase bg-green-100 text-green-700 px-2 py-0.5 rounded dark:bg-green-900/40 dark:text-green-300">
									{job.status}
								</span>
							</div>
							<p class="text-xs text-gray-500 dark:text-gray-400 truncate">
								{job.query || 'No description provided'}
							</p>
							<div class="mt-2 text-xs text-gray-400">
								Started {formatDate(job.created_at)}
							</div>
						</div>
						<button 
							onclick={() => handleResumeJob(job)}
							class="shrink-0 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500"
						>
							View
						</button>
					</div>
				{/each}
			</div>
		</div>
		{/if}

		<!-- Completed Jobs Section -->
		{#if completedJobs.length > 0}
		<div class="mt-8">
			<h3 class="mb-4 text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
				<svg class="h-5 w-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
				</svg>
				Completed Jobs
			</h3>
			<div class="overflow-hidden rounded-2xl border border-slate-200/70 bg-white/95 shadow-sm dark:border-slate-700 dark:bg-slate-900/80">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
					<thead class="bg-gray-50/50 dark:bg-gray-800/50">
						<tr>
							<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Crew</th>
							<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Task</th>
							<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Date</th>
							<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Status</th>
							<th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Action</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200 bg-white dark:divide-gray-700 dark:bg-gray-900">
						{#each completedJobs as job}
							<tr class="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
								<td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
									{job.crew_name}
								</td>
								<td class="px-6 py-4 text-sm text-gray-500 dark:text-gray-400 max-w-xs truncate">
									{job.query}
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
									{formatDate(job.created_at)}
								</td>
								<td class="px-6 py-4 whitespace-nowrap">
									<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium
										{job.status === 'completed' ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' : 
										 job.status === 'failed' ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400' : 
										 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300'}">
										{job.status}
									</span>
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
									<button 
										onclick={() => handleResumeJob(job)}
										class="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
									>
										View Results
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{/if}

		<!-- My Crews Table -->
		<div class="mt-10">
			<h3 class="mb-4 text-lg font-semibold text-gray-900 dark:text-white">My Crews</h3>
			<div
				class="overflow-hidden rounded-2xl border border-slate-200/70 bg-white/95 shadow-xl shadow-slate-200/60 backdrop-blur dark:border-slate-700 dark:bg-slate-900/80 dark:shadow-black/30"
			>
				<div class="overflow-x-auto">
					<table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
						<thead class="bg-slate-50/80 dark:bg-slate-900/80">
							<tr>
								<th
									class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
								>
									Name
								</th>
								<th
									class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
								>
									Agents
								</th>
								<th
									class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
								>
									Execution Mode
								</th>
								<th
									class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
								>
									Created
								</th>
								<th
									class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
								>
									Actions
								</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-200 bg-white dark:divide-gray-700 dark:bg-gray-800">
							{#if crewsLoading}
								<tr>
									<td
										colspan="5"
										class="px-6 py-8 text-center text-sm text-gray-500 dark:text-gray-400"
									>
										<div class="flex items-center justify-center gap-2">
											<div
												class="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"
											></div>
											Loading crews...
										</div>
									</td>
								</tr>
							{:else if crewsError}
								<tr>
									<td
										colspan="5"
										class="px-6 py-8 text-center text-sm text-red-600 dark:text-red-400"
									>
										{crewsError}
									</td>
								</tr>
							{:else if !crews.length}
								<tr>
									<td colspan="5" class="px-6 py-8 text-center">
										<p class="text-sm text-gray-500 dark:text-gray-400">No crews yet</p>
										<p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
											Create your first crew to get started!
										</p>
									</td>
								</tr>
							{:else}
								{#each crews as crewItem (crewItem.crew_id)}
									<tr class="transition-colors hover:bg-gray-50 dark:hover:bg-gray-700">
										<td class="whitespace-nowrap px-6 py-4">
											<div class="flex flex-col">
												<button 
													class="text-left text-sm font-medium capitalize text-gray-900 hover:text-green-600 hover:underline dark:text-white dark:hover:text-green-400"
													onclick={() => handleAskCrew(crewItem)}
												>
													{crewItem.name}
												</button>
												<span class="text-xs text-gray-500 dark:text-gray-400">
													{crewItem.description}
												</span>
											</div>
										</td>
										<td class="whitespace-nowrap px-6 py-4 text-sm text-gray-900 dark:text-white">
											{crewItem.agent_count ?? '—'}
										</td>
										<td
											class="whitespace-nowrap px-6 py-4 text-sm capitalize text-gray-900 dark:text-white"
										>
											<span class={getExecutionModeClass(crewItem.execution_mode)}>
												<span class="h-2 w-2 rounded-full bg-white/80"></span>
												{getExecutionModeLabel(crewItem.execution_mode)}
											</span>
										</td>
										<td
											class="whitespace-nowrap px-6 py-4 text-sm text-gray-500 dark:text-gray-400"
										>
											{formatDate(crewItem.created_at)}
										</td>
										<td class="whitespace-nowrap px-6 py-4 text-sm">
											<div class="flex items-center gap-3">
												<button
													onclick={() => handleAskCrew(crewItem)}
													class="cursor-pointer text-green-600 transition-colors hover:text-green-800 dark:text-green-400 dark:hover:text-green-300"
												>
													Ask
												</button>
												<button
													onclick={() => handleViewCrew(crewItem.crew_id)}
													class="cursor-pointer text-blue-600 transition-colors hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
												>
													Edit
												</button>
												<button
													onclick={() => handleDeleteClick(crewItem)}
													class="cursor-pointer text-red-600 transition-colors hover:text-red-800 dark:text-red-400 dark:hover:text-red-300"
												>
													Delete
												</button>
											</div>
										</td>
									</tr>
								{/each}
							{/if}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- Delete Confirmation Dialog -->
<ConfirmDialog
	isOpen={showDeleteDialog}
	title="Delete Crew"
	message="Are you sure you want to delete '{crewToDelete?.name}'? This action cannot be undone."
	confirmText="Delete"
	cancelText="Cancel"
	isDangerous={true}
	onconfirm={handleConfirmDelete}
	oncancel={handleCancelDelete}
/>

<!-- Crew Execution Wizard (replaces Ask Crew Modal) -->
<CrewExecutionWizard 
	showModal={showAskModal} 
	crew={crewToAsk} 
	initialJobId={selectedJobId}
    initialJobStatus={selectedJobStatus}
	onClose={() => {
		handleCloseAskModal();
		selectedJobId = null;
        selectedJobStatus = null;
		fetchCrews(); // Refresh active jobs list on close
	}} 
/>
