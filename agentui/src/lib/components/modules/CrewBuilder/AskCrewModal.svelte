<script>
	import { crew as crewApi } from '$lib/api/crew';
	import { markdownToHtml } from '$lib/utils/markdown';

	let { showModal = false, crew = null, onClose = () => {} } = $props();

	const executionModeMeta = {
		sequential: {
			label: 'Sequential',
			description: "Run agents one after another using the crew's defined order."
		},
		parallel: {
			label: 'Parallel',
			description: 'Execute agents simultaneously with shared or per-agent prompts.'
		},
		loop: { label: 'Loop', description: 'Iterate through agents until the stop condition is met.' },
		flow: {
			label: 'Flow',
			description: "Follow the crew's flow configuration to determine execution order."
		}
	};

	let crews = $state([]);
	let crewsLoading = $state(false);
	let crewsError = $state('');
	let selectedCrewId = $state('');

	let crewDetails = $state(null);
	let crewDetailsLoading = $state(false);
	let crewDetailsError = $state('');
	let lastLoadedCrewId = $state(null);

	let question = $state('');
	let parallelInputMode = $state('shared');
	let parallelSharedTask = $state('');
	let parallelAgentTasks = $state({});
	let parallelSynthesisPrompt = $state('');
	let parallelAllResults = $state(false);
	let loopInitialTask = $state('');
	let loopCondition = $state('');
	let loopMaxIterations = $state(4);
	let loopAgentSequence = $state([]);
	let loopSynthesisPrompt = $state('');
	let flowInitialTask = $state('');
	let flowSynthesisPrompt = $state('');

	let jobStatus = $state(null);
	let statusMessage = $state('');
	let jobError = $state('');
	let isSubmitting = $state(false);

	let currentMode = $state('sequential');
	let modeLocked = $state(false);
	let draggingIndex = $state(null);

	let selectedCrew = $derived(crews.find((c) => c.crew_id === selectedCrewId) ?? null);

	let rawAgentResponses = $derived(
		jobStatus?.result?.response && typeof jobStatus.result.response === 'object'
			? Object.entries(jobStatus.result.response)
			: []
	);

	let agentResponses = $derived(
		rawAgentResponses.map(([name, details]) => ({
			name,
			input: typeof details?.input === 'string' ? details.input : undefined,
			outputHtml:
				typeof details?.output === 'string' && details.output.trim()
					? markdownToHtml(details.output)
					: ''
		}))
	);

	let finalOutputRaw = $derived(jobStatus?.result?.output ?? null);
	let finalOutputHtml = $derived(
		typeof finalOutputRaw === 'string' && finalOutputRaw.trim()
			? markdownToHtml(finalOutputRaw)
			: ''
	);
	let finalOutputList = $derived(Array.isArray(finalOutputRaw) ? finalOutputRaw : []);
	let finalOutputListHtml = $derived(
		finalOutputList.map((item) => {
			if (typeof item === 'string') {
				return item.trim() ? markdownToHtml(item) : '';
			}
			try {
				return markdownToHtml('```json\n' + JSON.stringify(item, null, 2) + '\n```');
			} catch (error) {
				return markdownToHtml(String(item));
			}
		})
	);

	$effect(() => {
		if (showModal) {
			fetchCrews();
			if (crew?.crew_id) {
				selectedCrewId = crew.crew_id;
			}
		} else {
			resetAll();
		}
	});

	$effect(() => {
		if (selectedCrewId && selectedCrewId !== lastLoadedCrewId) {
			loadCrewDetails(selectedCrewId);
		} else if (!selectedCrewId) {
			crewDetails = null;
			crewDetailsError = '';
			lastLoadedCrewId = null;
			loopAgentSequence = [];
			initializeAgentPrompts([]);
		}
	});

	$effect(() => {
		if (!modeLocked && selectedCrew) {
			const defaultMode =
				crewDetails?.execution_mode ?? selectedCrew?.execution_mode ?? 'sequential';
			if (currentMode !== defaultMode) currentMode = defaultMode;
		}
	});

	function initializeAgentPrompts(agentIds) {
		const prompts = {};
		for (const id of agentIds) if (typeof id === 'string' && id) prompts[id] = '';
		parallelAgentTasks = prompts;
	}

	function setParallelAgentTask(agentId, value) {
		parallelAgentTasks = { ...parallelAgentTasks, [agentId]: value };
	}

	function getAgentDisplayName(agentId) {
		const agent = crewDetails?.agents?.find((item) => item.agent_id === agentId);
		return agent?.name?.trim() || agentId;
	}

	function getExecutionModeLabel(mode) {
		if (!mode) return '';
		const meta = executionModeMeta[mode];
		return meta?.label ?? mode;
	}

	function moveAgentInSequence(fromIndex, toIndex) {
		if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
		const updated = [...loopAgentSequence];
		if (fromIndex >= updated.length) return;
		const [moved] = updated.splice(fromIndex, 1);
		const clampedIndex = Math.min(Math.max(toIndex, 0), updated.length);
		updated.splice(clampedIndex, 0, moved);
		loopAgentSequence = updated;
	}

	function moveAgentUp(index) {
		if (index <= 0) return;
		moveAgentInSequence(index, index - 1);
	}

	function moveAgentDown(index) {
		if (index >= loopAgentSequence.length - 1) return;
		moveAgentInSequence(index, index + 1);
	}

	function handleDragStart(event, index) {
		draggingIndex = index;
		if (event.dataTransfer) {
			event.dataTransfer.effectAllowed = 'move';
			event.dataTransfer.setData('text/plain', index.toString());
		}
	}

	function handleDragOver(event) {
		event.preventDefault();
		if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
	}

	function handleDrop(event, index) {
		event.preventDefault();
		const data = event.dataTransfer?.getData('text/plain');
		const fromIndex = draggingIndex ?? (data ? parseInt(data, 10) : -1);
		if (Number.isNaN(fromIndex) || fromIndex < 0) {
			draggingIndex = null;
			return;
		}
		moveAgentInSequence(fromIndex, index);
		draggingIndex = null;
	}

	function handleDropAtEnd(event) {
		event.preventDefault();
		const data = event.dataTransfer?.getData('text/plain');
		const fromIndex = draggingIndex ?? (data ? parseInt(data, 10) : -1);
		if (Number.isNaN(fromIndex) || fromIndex < 0) {
			draggingIndex = null;
			return;
		}
		const updated = [...loopAgentSequence];
		if (fromIndex >= updated.length) {
			draggingIndex = null;
			return;
		}
		const [moved] = updated.splice(fromIndex, 1);
		updated.push(moved);
		loopAgentSequence = updated;
		draggingIndex = null;
	}

	function handleDragEnd() {
		draggingIndex = null;
	}

	async function fetchCrews() {
		crewsLoading = true;
		crewsError = '';
		try {
			const response = await crewApi.listCrews();
			crews = Array.isArray(response?.crews) ? response.crews : [];
		} catch (error) {
			console.error('Failed to load crews', error);
			crewsError =
				error?.response?.data?.message || error?.message || 'Unable to load crews at this time.';
			crews = [];
		} finally {
			crewsLoading = false;
		}
	}

	async function loadCrewDetails(crewId) {
		crewDetailsLoading = true;
		crewDetailsError = '';
		try {
			const response = await crewApi.getCrewById(crewId);
			const details = response ?? {};
			const agents = Array.isArray(details?.agents)
				? details.agents.filter((agent) => typeof agent?.agent_id === 'string')
				: [];
			crewDetails = { ...details, agents };
			lastLoadedCrewId = crewId;
			loopAgentSequence = agents.map((agent) => agent.agent_id);
			initializeAgentPrompts(loopAgentSequence);
			resetQuestion();
		} catch (error) {
			console.error('Failed to load crew details', error);
			crewDetails = null;
			loopAgentSequence = [];
			initializeAgentPrompts([]);
			crewDetailsError =
				error?.response?.data?.message ||
				error?.message ||
				'Unable to load crew details. Please try again.';
			lastLoadedCrewId = crewId;
			resetQuestion();
		} finally {
			crewDetailsLoading = false;
		}
	}

	async function handleSubmit(event) {
		event.preventDefault();
		jobError = '';

		if (!selectedCrewId) {
			jobError = 'Please choose a crew to ask your question.';
			return;
		}

		const executionOptions = { execution_mode: currentMode };
		let queryPayload;

		if (currentMode === 'parallel') {
			if (parallelInputMode === 'shared') {
				if (!parallelSharedTask.trim()) {
					jobError = 'Please provide a shared task for the crew.';
					return;
				}
				queryPayload = parallelSharedTask.trim();
			} else {
				const entries = Object.entries(parallelAgentTasks ?? {});
				if (!entries.length) {
					jobError = 'No agents available to run in parallel.';
					return;
				}
				const missingPrompts = entries.filter(([, prompt]) => !prompt?.trim());
				if (missingPrompts.length) {
					jobError = 'Please provide a prompt for each agent.';
					return;
				}
				const customTasks = {};
				for (const [agentId, prompt] of entries) customTasks[agentId] = prompt.trim();
				queryPayload = customTasks;
			}
			if (parallelSynthesisPrompt.trim())
				executionOptions.synthesis_prompt = parallelSynthesisPrompt.trim();
			const kwargs = {};
			if (parallelAllResults) kwargs.all_results = true;
			executionOptions.kwargs = kwargs;
		} else if (currentMode === 'loop') {
			if (!loopInitialTask.trim()) {
				jobError = 'Please provide an initial task to start the loop.';
				return;
			}
			if (!loopCondition.trim()) {
				jobError = 'Please provide a condition to stop the loop.';
				return;
			}
			const iterations = Math.max(1, Number(loopMaxIterations) || 1);
			queryPayload = loopInitialTask.trim();
			const kwargs = { condition: loopCondition.trim(), max_iterations: iterations };
			if (loopAgentSequence.length) kwargs.agent_sequence = [...loopAgentSequence];
			if (loopSynthesisPrompt.trim())
				executionOptions.synthesis_prompt = loopSynthesisPrompt.trim();
			executionOptions.kwargs = kwargs;
		} else if (currentMode === 'flow') {
			if (!flowInitialTask.trim()) {
				jobError = 'Please provide an initial task for the flow execution.';
				return;
			}
			queryPayload = flowInitialTask.trim();
			if (flowSynthesisPrompt.trim())
				executionOptions.synthesis_prompt = flowSynthesisPrompt.trim();
		} else {
			if (!question.trim()) {
				jobError = 'Please provide a question or task for the crew.';
				return;
			}
			queryPayload = question.trim();
		}

		isSubmitting = true;
		statusMessage = '';
		jobStatus = null;

		try {
			const execution = await crewApi.executeCrew(selectedCrewId, queryPayload, executionOptions);
			jobStatus = execution;
			statusMessage = execution?.message ?? 'Crew execution started.';
			if (!execution?.job_id)
				throw new Error('The crew execution did not return a job identifier.');
			const finalStatus = await crewApi.pollJobUntilComplete(execution.job_id, 2000, 120);
			jobStatus = finalStatus;
			statusMessage = finalStatus?.message ?? 'Crew status: ' + (finalStatus?.status ?? 'unknown');
		} catch (error) {
			console.error('Failed to execute crew', error);
			jobError =
				error?.response?.data?.message ||
				error?.message ||
				'Unable to execute the crew. Please try again.';
		} finally {
			isSubmitting = false;
		}
	}

	function resetQuestion() {
		question = '';
		parallelSharedTask = '';
		parallelSynthesisPrompt = '';
		parallelAllResults = false;
		parallelInputMode = 'shared';
		loopInitialTask = '';
		loopCondition = '';
		loopMaxIterations = 4;
		loopSynthesisPrompt = '';
		flowInitialTask = '';
		flowSynthesisPrompt = '';
		if (loopAgentSequence.length) {
			initializeAgentPrompts(loopAgentSequence);
		} else {
			parallelAgentTasks = {};
		}
		jobStatus = null;
		jobError = '';
		statusMessage = '';
	}

	function resetAll() {
		selectedCrewId = '';
		crews = [];
		crewDetails = null;
		lastLoadedCrewId = null;
		currentMode = 'sequential';
		modeLocked = false;
		resetQuestion();
	}

	function handleModeChange(mode) {
		if (currentMode !== mode) currentMode = mode;
		modeLocked = true;
		jobStatus = null;
		jobError = '';
		statusMessage = '';
	}

	function handleClose() {
		if (!isSubmitting) onClose();
	}

	function retryLoadCrewDetails() {
		if (!selectedCrewId) return;
		lastLoadedCrewId = null;
		loadCrewDetails(selectedCrewId);
	}
</script>

{#if showModal}
	<div class="fixed inset-0 z-50 overflow-y-auto bg-black/50 backdrop-blur-sm">
		<div class="flex min-h-screen items-center justify-center p-4">
			<div
				class="w-full max-w-6xl rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800"
			>
				<!-- Header -->
				<div
					class="flex items-center justify-between border-b border-gray-200 bg-gradient-to-r from-green-600 to-green-700 px-6 py-4 dark:border-gray-700 dark:from-green-700 dark:to-green-800"
				>
					<div>
						<h2 class="text-2xl font-bold text-white">Ask a Crew</h2>
						<p class="mt-1 text-sm text-white/80">
							Select a crew and configure how it should run. Review both the final outcome and each
							agent's contribution.
						</p>
					</div>
					<button
						onclick={handleClose}
						disabled={isSubmitting}
						class="rounded-lg p-2 text-white/80 transition-colors hover:bg-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
						aria-label="Close"
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

				<!-- Content -->
				<div class="max-h-[calc(100vh-150px)] overflow-y-auto p-6">
					<form onsubmit={handleSubmit} class="space-y-6">
						<!-- Crew Selection -->
						<div class="space-y-2">
							<label
								class="block text-sm font-semibold text-gray-800 dark:text-gray-200"
								for="crew-select"
							>
								Select crew
							</label>
							{#if crewsLoading}
								<div
									class="flex items-center gap-3 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-300"
								>
									<div
										class="h-4 w-4 animate-spin rounded-full border-2 border-gray-600 border-t-transparent dark:border-gray-400"
									></div>
									<span>Loading crews…</span>
								</div>
							{:else if crewsError}
								<div
									class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-800 dark:bg-red-900 dark:text-red-200"
								>
									<span>{crewsError}</span>
									<button
										type="button"
										class="ml-3 rounded bg-red-600 px-3 py-1 text-white hover:bg-red-700"
										onclick={() => fetchCrews()}
									>
										Retry
									</button>
								</div>
							{:else}
								<select
									class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
									id="crew-select"
									bind:value={selectedCrewId}
								>
									<option value="" disabled>Choose a crew to query</option>
									{#each crews as crewItem (crewItem.crew_id)}
										<option value={crewItem.crew_id}>
											{crewItem.name} — {crewItem.crew_id}
										</option>
									{/each}
								</select>
								{#if selectedCrew}
									<div class="space-y-2 text-sm text-gray-700 dark:text-gray-300">
										<p>
											<span class="font-semibold">Crew ID:</span>
											{selectedCrew.crew_id}
											<span class="mx-2">·</span>
											<span class="font-semibold">Default mode:</span>
											{selectedCrew.execution_mode || 'sequential'}
										</p>
										<p class="text-xs text-gray-600 dark:text-gray-400">
											{selectedCrew.description || 'No description provided'}
										</p>
										{#if crewDetails?.agents}
											<p class="text-xs text-gray-600 dark:text-gray-400">
												<span class="font-semibold text-gray-800 dark:text-gray-200">Agents:</span>
												{crewDetails.agents.length}
											</p>
										{/if}
									</div>
								{/if}
								{#if crewDetailsLoading}
									<div
										class="mt-3 flex items-center gap-3 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-3 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-300"
									>
										<div
											class="h-4 w-4 animate-spin rounded-full border-2 border-gray-600 border-t-transparent dark:border-gray-400"
										></div>
										<span>Loading crew details…</span>
									</div>
								{:else if crewDetailsError}
									<div
										class="mt-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800 dark:border-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
									>
										<span>{crewDetailsError}</span>
										<button
											type="button"
											class="ml-3 rounded bg-yellow-600 px-3 py-1 text-white hover:bg-yellow-700"
											onclick={retryLoadCrewDetails}
										>
											Retry
										</button>
									</div>
								{/if}
							{/if}
						</div>

						<!-- Execution Mode -->
						{#if selectedCrew}
							<div
								class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
							>
								<div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
									<div class="space-y-1">
										<span
											class="block text-sm font-semibold uppercase tracking-wide text-gray-800 dark:text-gray-200"
										>
											Execution mode
										</span>
										<p class="text-xs text-gray-600 dark:text-gray-400">
											{executionModeMeta[currentMode].description}
										</p>
									</div>
									<div class="w-full max-w-xs">
										<label
											class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-400"
										>
											Mode
										</label>
										<select
											class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 capitalize text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
											bind:value={currentMode}
											onchange={(event) => handleModeChange(event.target.value)}
											disabled={isSubmitting || crewsLoading || crewDetailsLoading}
										>
											{#each Object.entries(executionModeMeta) as [value, meta] (value)}
												<option {value} class="capitalize">{meta.label}</option>
											{/each}
										</select>
									</div>
								</div>
								{#if crewDetails?.agents}
									<p class="mt-4 text-xs text-gray-600 dark:text-gray-400">
										<span class="font-semibold text-gray-800 dark:text-gray-200">Agents:</span>
										{crewDetails.agents.length}
									</p>
								{/if}
							</div>
						{/if}

						<!-- Sequential Mode -->
						{#if currentMode === 'sequential'}
							<div>
								<label
									class="mb-2 block text-sm font-medium text-gray-800 dark:text-gray-200"
									for="question"
								>
									Question
								</label>
								<textarea
									id="question"
									class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
									rows="5"
									bind:value={question}
									placeholder="Write your prompt using Markdown..."
									disabled={isSubmitting || crewsLoading}
								></textarea>
								<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
									Supports headings, lists, inline code, and more.
								</p>
							</div>
						{/if}

						<!-- Parallel Mode -->
						{#if currentMode === 'parallel'}
							<div class="space-y-6">
								<div
									class="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900"
								>
									<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
										<div>
											<h3 class="text-base font-semibold text-gray-900 dark:text-white">
												Parallel tasks
											</h3>
											<p class="text-sm text-gray-600 dark:text-gray-400">
												Choose how prompts are distributed across agents.
											</p>
										</div>
									</div>
									<div class="mt-4 flex flex-col gap-2 md:flex-row md:items-center">
										<label
											class="flex cursor-pointer items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
										>
											<input
												type="radio"
												class="h-4 w-4 text-green-600"
												value="shared"
												bind:group={parallelInputMode}
												disabled={isSubmitting || crewDetailsLoading}
											/>
											<span class="text-gray-900 dark:text-gray-100"
												>Single prompt for all agents</span
											>
										</label>
										<label
											class="flex cursor-pointer items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
										>
											<input
												type="radio"
												class="h-4 w-4 text-green-600"
												value="custom"
												bind:group={parallelInputMode}
												disabled={isSubmitting ||
													crewDetailsLoading ||
													!crewDetails?.agents?.length}
											/>
											<span class="text-gray-900 dark:text-gray-100">Custom prompt per agent</span>
										</label>
									</div>
									{#if parallelInputMode === 'shared'}
										<div class="mt-4">
											<label
												class="mb-2 block text-sm font-medium text-gray-800 dark:text-gray-200"
												for="parallel-shared"
											>
												Question
											</label>
											<textarea
												id="parallel-shared"
												class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
												rows="4"
												bind:value={parallelSharedTask}
												placeholder="Write your prompt using Markdown..."
												disabled={isSubmitting || crewsLoading || crewDetailsLoading}
											></textarea>
											<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
												This prompt will be sent to every agent.
											</p>
										</div>
									{:else}
										<div class="mt-4 space-y-4">
											{#if crewDetailsLoading}
												<div
													class="flex items-center gap-3 text-sm text-gray-700 dark:text-gray-300"
												>
													<div
														class="h-4 w-4 animate-spin rounded-full border-2 border-gray-600 border-t-transparent dark:border-gray-400"
													></div>
													<span>Loading agent details…</span>
												</div>
											{:else if crewDetailsError}
												<p class="text-sm text-red-600 dark:text-red-400">
													Crew details are unavailable. Retry loading above.
												</p>
											{:else if !crewDetails?.agents?.length}
												<p class="text-sm text-gray-600 dark:text-gray-400">
													This crew does not have any agents configured.
												</p>
											{:else}
												{#each crewDetails.agents as agent (agent.agent_id)}
													<div
														class="space-y-2 rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-600 dark:bg-gray-800"
													>
														<div class="flex flex-wrap items-center justify-between gap-2">
															<span class="font-semibold text-gray-900 dark:text-white">
																{agent.name?.trim() || agent.agent_id}
															</span>
															<span
																class="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700 dark:bg-gray-700 dark:text-gray-300"
															>
																{agent.agent_id}
															</span>
														</div>
														<textarea
															class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
															rows="3"
															value={parallelAgentTasks[agent.agent_id] ?? ''}
															oninput={(event) =>
																setParallelAgentTask(agent.agent_id, event.currentTarget.value)}
															placeholder="Enter a prompt for this agent"
															disabled={isSubmitting}
														></textarea>
													</div>
												{/each}
											{/if}
										</div>
									{/if}
								</div>

								<div
									class="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900"
								>
									<h3 class="text-base font-semibold text-gray-900 dark:text-white">Synthesis</h3>
									<p class="text-sm text-gray-600 dark:text-gray-400">
										Provide an optional synthesis prompt to summarize the combined results.
									</p>
									<textarea
										class="mt-3 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
										rows="3"
										bind:value={parallelSynthesisPrompt}
										placeholder="Ask the crew to synthesize the parallel outputs (optional)"
										disabled={isSubmitting}
									></textarea>
									<label
										class="mt-4 flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
									>
										<span>Return each agent result separately</span>
										<input
											type="checkbox"
											class="h-5 w-5 rounded text-green-600 focus:ring-green-500"
											bind:checked={parallelAllResults}
											disabled={isSubmitting}
										/>
									</label>
									<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
										When enabled, the final output will be a list of each agent&apos;s response.
									</p>
								</div>
							</div>
						{/if}

						<!-- Loop Mode -->
						{#if currentMode === 'loop'}
							<div class="space-y-6">
								<div
									class="space-y-4 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900"
								>
									<div>
										<h3 class="text-base font-semibold text-gray-900 dark:text-white">
											Loop configuration
										</h3>
										<p class="text-sm text-gray-600 dark:text-gray-400">
											Provide the initial task and stopping criteria for the loop.
										</p>
									</div>
									<div>
										<label
											class="mb-2 block text-sm font-medium text-gray-800 dark:text-gray-200"
											for="loop-task"
										>
											Question
										</label>
										<textarea
											id="loop-task"
											class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
											rows="4"
											bind:value={loopInitialTask}
											placeholder="Write your prompt using Markdown..."
											disabled={isSubmitting || crewsLoading || crewDetailsLoading}
										></textarea>
										<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
											Initial task for the first iteration.
										</p>
									</div>
									<div class="grid gap-4 md:grid-cols-2">
										<div>
											<label
												class="mb-2 block text-sm font-medium text-gray-800 dark:text-gray-200"
												for="loop-condition"
											>
												Stopping condition
											</label>
											<input
												id="loop-condition"
												type="text"
												class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
												bind:value={loopCondition}
												placeholder="Stop when..."
												disabled={isSubmitting}
											/>
											<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
												Example: "Stop when the reviewer marks the report as FINAL".
											</p>
										</div>
										<div>
											<label
												class="mb-2 block text-sm font-medium text-gray-800 dark:text-gray-200"
												for="loop-iterations"
											>
												Max iterations
											</label>
											<input
												id="loop-iterations"
												type="number"
												min="1"
												class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
												bind:value={loopMaxIterations}
												disabled={isSubmitting}
											/>
											<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
												Safety limit for how many times the loop can run.
											</p>
										</div>
									</div>
								</div>

								<div
									class="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900"
								>
									<h3 class="text-base font-semibold text-gray-900 dark:text-white">
										Loop Sequence
									</h3>
									<p class="text-sm text-gray-600 dark:text-gray-400">
										Drag agents to reorder the execution loop.
									</p>

									{#if crewDetailsLoading}
										<div class="mt-4 flex items-center justify-center py-6 text-gray-500">
											<span class="loading loading-spinner"></span>
											<span class="ml-2">Loading agents...</span>
										</div>
									{:else if !crewDetails?.agents?.length}
										<div class="mt-4 text-center text-sm text-gray-500">
											No agents available for sequencing.
										</div>
									{:else}
										<div class="mt-4 space-y-2">
											{#each loopAgentSequence as agentId, i (agentId)}
												<div
													class="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 shadow-sm transition-all hover:shadow-md dark:border-gray-600 dark:bg-gray-800 {draggingIndex ===
													i
														? 'opacity-50'
														: ''}"
													draggable="true"
													ondragstart={(e) => handleDragStart(e, i)}
													ondragover={handleDragOver}
													ondrop={(e) => handleDrop(e, i)}
													ondragend={handleDragEnd}
													role="listitem"
												>
													<div class="cursor-grab text-gray-400 hover:text-gray-600">
														<svg
															class="h-5 w-5"
															fill="none"
															stroke="currentColor"
															viewBox="0 0 24 24"
														>
															<path
																stroke-linecap="round"
																stroke-linejoin="round"
																stroke-width="2"
																d="M4 8h16M4 16h16"
															/>
														</svg>
													</div>
													<div
														class="flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-600 dark:bg-gray-700 dark:text-gray-300"
													>
														{i + 1}
													</div>
													<div class="flex-1">
														<span class="font-medium text-gray-900 dark:text-white">
															{getAgentDisplayName(agentId)}
														</span>
														{#if agentId !== getAgentDisplayName(agentId)}
															<span class="ml-2 text-xs text-gray-500">({agentId})</span>
														{/if}
													</div>
													<div class="flex items-center">
														<button
															type="button"
															class="p-1 text-gray-400 hover:text-gray-600 disabled:opacity-30"
															disabled={i === 0}
															onclick={() => moveAgentUp(i)}
														>
															<svg
																class="h-4 w-4"
																fill="none"
																stroke="currentColor"
																viewBox="0 0 24 24"
															>
																<path
																	stroke-linecap="round"
																	stroke-linejoin="round"
																	stroke-width="2"
																	d="M5 15l7-7 7 7"
																/>
															</svg>
														</button>
														<button
															type="button"
															class="p-1 text-gray-400 hover:text-gray-600 disabled:opacity-30"
															disabled={i === loopAgentSequence.length - 1}
															onclick={() => moveAgentDown(i)}
														>
															<svg
																class="h-4 w-4"
																fill="none"
																stroke="currentColor"
																viewBox="0 0 24 24"
															>
																<path
																	stroke-linecap="round"
																	stroke-linejoin="round"
																	stroke-width="2"
																	d="M19 9l-7 7-7-7"
																/>
															</svg>
														</button>
													</div>
												</div>
											{/each}
										</div>
									{/if}
								</div>

								<div
									class="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900"
								>
									<h3 class="text-base font-semibold text-gray-900 dark:text-white">Synthesis</h3>
									<textarea
										class="mt-3 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
										rows="3"
										bind:value={loopSynthesisPrompt}
										placeholder="Optional synthesis prompt for loop results..."
										disabled={isSubmitting}
									></textarea>
								</div>
							</div>
						{/if}

						{#if jobError}
							<div
								class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-900/30 dark:text-red-200"
							>
								{jobError}
							</div>
						{/if}

						<div class="flex justify-end gap-3 pt-2">
							<button
								type="button"
								onclick={handleClose}
								class="rounded-lg px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
								disabled={isSubmitting}
							>
								Cancel
							</button>
							<button
								type="submit"
								class="flex items-center gap-2 rounded-lg bg-green-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-green-700 focus:outline-none focus:ring-4 focus:ring-green-200 disabled:opacity-50 dark:bg-green-600 dark:hover:bg-green-700 dark:focus:ring-green-900"
								disabled={isSubmitting}
							>
								{#if isSubmitting}
									<div
										class="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
									></div>
									Starting...
								{:else}
									Execute Crew
								{/if}
							</button>
						</div>
					</form>
				</div>
			</div>
		</div>
	</div>
{/if}
