<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { page } from '$app/stores';
  import { crew as crewApi } from '$lib/api';
  import type { CrewExecutionMode } from '$lib/api/crew/crew';
  import MarkdownEditor from '$lib/components/MarkdownEditor.svelte';
  import JsonViewer from '$lib/components/JsonViewer.svelte';
  import { markdownToHtml } from '$lib/utils/markdown';
  import { LoadingSpinner } from '$lib/components';

  type CrewExecutionMode = 'sequential' | 'parallel' | 'loop' | 'flow';

  interface CrewSummary {
    crew_id: string;
    name: string;
    description?: string;
    execution_mode?: CrewExecutionMode;
  }

  interface CrewAgentSummary {
    agent_id: string;
    name?: string | null;
  }

  interface CrewDetails extends CrewSummary {
    agents?: CrewAgentSummary[];
  }

  interface CrewJobStatus {
    job_id: string;
    crew_id: string;
    status: string;
    message?: string;
    result?: {
      output?: unknown;
      response?: Record<string, { input?: string; output?: string }>;
    };
    execution_mode?: string;
    [key: string]: unknown;
  }

  interface AgentResponse {
    input?: string;
    output?: string;
  }

  interface AgentResponseView {
    name: string;
    input?: string;
    outputHtml: string;
  }

  let crews: CrewSummary[] = [];
  let crewsLoading = false;
  let crewsError = '';
  let selectedCrewId = '';

  let crewDetails: CrewDetails | null = null;
  let crewDetailsLoading = false;
  let crewDetailsError = '';
  let lastLoadedCrewId: string | null = null;
  let pendingCrewId: string | null = null;
  let detailsRequestId = 0;

  let question = '';
  let parallelInputMode: 'shared' | 'custom' = 'shared';
  let parallelSharedTask = '';
  let parallelAgentTasks: Record<string, string> = {};
  let parallelSynthesisPrompt = '';
  let parallelAllResults = false;
  let loopInitialTask = '';
  let loopCondition = '';
  let loopMaxIterations = 4;
  let loopAgentSequence: string[] = [];
  let loopSynthesisPrompt = '';
  let flowInitialTask = '';
  let flowSynthesisPrompt = '';

  let jobStatus: CrewJobStatus | null = null;
  let statusMessage = '';
  let jobError = '';
  let isSubmitting = false;

  let rawAgentResponses: [string, AgentResponse][] = [];
  let agentResponses: AgentResponseView[] = [];
  const crewSelectId = 'crew-select';

  let selectedCrew: CrewSummary | null = null;
  const executionModeMeta = {
    sequential: {
      label: 'Sequential',
      description: 'Run agents one after another using the crew\'s defined order.'
    },
    parallel: {
      label: 'Parallel',
      description: 'Execute agents simultaneously with shared or per-agent prompts.'
    },
    loop: {
      label: 'Loop',
      description: 'Iterate through agents until the stop condition is met.'
    },
    flow: {
      label: 'Flow',
      description: 'Follow the crew\'s flow configuration to determine execution order.'
    }
  } satisfies Record<CrewExecutionMode, { label: string; description: string }>;

  const executionModeOptions = (
    Object.entries(executionModeMeta) as [CrewExecutionMode, { label: string; description: string }][]
  ).map(([value, meta]) => ({ value, ...meta }));

  let currentMode: CrewExecutionMode = 'sequential';
  let modeLocked = false;
  let lastModeCrewId: string | null = null;
  let finalOutputRaw: unknown = null;
  let finalOutputHtml = '';
  let finalOutputList: unknown[] = [];
  let finalOutputListHtml: string[] = [];
  let draggingIndex: number | null = null;

  $: selectedCrew = crews.find((crewItem) => crewItem.crew_id === selectedCrewId) ?? null;
  $: if (selectedCrewId !== lastModeCrewId) {
    modeLocked = false;
    lastModeCrewId = selectedCrewId || null;
  }
  $: if (!selectedCrewId) {
    if (currentMode !== 'sequential') {
      currentMode = 'sequential';
    }
  } else if (!modeLocked) {
    const defaultMode = (crewDetails?.execution_mode ?? selectedCrew?.execution_mode ?? 'sequential') as CrewExecutionMode;
    if (currentMode !== defaultMode) {
      currentMode = defaultMode;
    }
  }
  $: rawAgentResponses =
    jobStatus?.result?.response && typeof jobStatus.result.response === 'object'
      ? (Object.entries(jobStatus.result.response) as [string, AgentResponse][])
      : [];
  $: agentResponses = rawAgentResponses.map(([name, details]) => ({
    name,
    input: typeof details?.input === 'string' ? details.input : undefined,
    outputHtml:
      typeof details?.output === 'string' && details.output.trim()
        ? markdownToHtml(details.output)
        : ''
  }));
  $: finalOutputRaw = jobStatus?.result?.output ?? null;
  $: finalOutputHtml =
    typeof finalOutputRaw === 'string' && finalOutputRaw.trim()
      ? markdownToHtml(finalOutputRaw)
      : '';
  $: finalOutputList = Array.isArray(finalOutputRaw) ? (finalOutputRaw as unknown[]) : [];
  $: finalOutputListHtml = finalOutputList.map((item) => {
    if (typeof item === 'string') {
      return item.trim() ? markdownToHtml(item) : '';
    }
    try {
      return markdownToHtml('```json\n' + JSON.stringify(item, null, 2) + '\n```');
    } catch (error) {
      return markdownToHtml(String(item));
    }
  });
  $: if (selectedCrewId) {
    if (selectedCrewId !== pendingCrewId && selectedCrewId !== lastLoadedCrewId) {
      pendingCrewId = selectedCrewId;
      void loadCrewDetails(selectedCrewId);
    }
  } else if (lastLoadedCrewId || pendingCrewId) {
    crewDetails = null;
    crewDetailsError = '';
    lastLoadedCrewId = null;
    pendingCrewId = null;
    loopAgentSequence = [];
    initializeAgentPrompts([]);
  }

  function extractErrorMessage(error: unknown, fallback: string) {
    let responseMessage: string | undefined;

    if (
      typeof error === 'object' &&
      error !== null &&
      'response' in error &&
      (error as Record<string, unknown>).response &&
      typeof (error as Record<string, unknown>).response === 'object'
    ) {
      const response = (error as { response?: Record<string, unknown> }).response;
      const data = response?.data;
      if (
        data &&
        typeof data === 'object' &&
        'message' in data &&
        typeof (data as Record<string, unknown>).message === 'string'
      ) {
        responseMessage = (data as { message?: string }).message;
      }
    }

    if (responseMessage) {
      return responseMessage;
    }

    if (error instanceof Error && typeof error.message === 'string') {
      return error.message;
    }

    return fallback;
  }

  function initializeAgentPrompts(agentIds: string[]) {
    const prompts: Record<string, string> = {};
    for (const id of agentIds) {
      if (typeof id === 'string' && id) {
        prompts[id] = '';
      }
    }
    parallelAgentTasks = prompts;
  }

  function setParallelAgentTask(agentId: string, value: string) {
    parallelAgentTasks = { ...parallelAgentTasks, [agentId]: value };
  }

  function getAgentDisplayName(agentId: string) {
    const agent = crewDetails?.agents?.find((item) => item.agent_id === agentId);
    return agent?.name?.trim() || agentId;
  }

  function getExecutionModeLabel(mode?: string | null) {
    if (!mode) {
      return '';
    }
    const meta = executionModeMeta[mode as CrewExecutionMode];
    return meta?.label ?? mode;
  }

  function moveAgentInSequence(fromIndex: number, toIndex: number) {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) {
      return;
    }
    const updated = [...loopAgentSequence];
    if (fromIndex >= updated.length) {
      return;
    }
    const [moved] = updated.splice(fromIndex, 1);
    const clampedIndex = Math.min(Math.max(toIndex, 0), updated.length);
    updated.splice(clampedIndex, 0, moved);
    loopAgentSequence = updated;
  }

  function moveAgentUp(index: number) {
    if (index <= 0) {
      return;
    }
    moveAgentInSequence(index, index - 1);
  }

  function moveAgentDown(index: number) {
    if (index >= loopAgentSequence.length - 1) {
      return;
    }
    moveAgentInSequence(index, index + 1);
  }

  function handleDragStart(event: DragEvent, index: number) {
    draggingIndex = index;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', index.toString());
    }
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'move';
    }
  }

  function handleDrop(event: DragEvent, index: number) {
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

  function handleDropAtEnd(event: DragEvent) {
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

  async function fetchCrews(initialCrewId?: string | null) {
    crewsLoading = true;
    crewsError = '';

    try {
      const response = await crewApi.listCrews();
      const list = Array.isArray(response?.crews) ? (response.crews as CrewSummary[]) : [];
      crews = list.map((item) => ({
        ...item,
        execution_mode:
          typeof item.execution_mode === 'string'
            ? (item.execution_mode as CrewExecutionMode)
            : undefined
      }));

      if (initialCrewId) {
        const exists = list.some((item) => item.crew_id === initialCrewId);
        if (exists) {
          selectedCrewId = initialCrewId;
        }
      }
    } catch (error) {
      console.error('Failed to load crews', error);
      crewsError = extractErrorMessage(error, 'Unable to load crews at this time.');
      crews = [];
    } finally {
      crewsLoading = false;
    }
  }

  async function loadCrewDetails(crewId: string) {
    pendingCrewId = crewId;
    const currentRequest = ++detailsRequestId;
    crewDetailsLoading = true;
    crewDetailsError = '';

    try {
      const response = await crewApi.getCrewById(crewId);
      if (currentRequest !== detailsRequestId) {
        return;
      }

      const details = (response ?? {}) as CrewDetails;
      const agents = Array.isArray(details?.agents)
        ? details.agents.filter((agent): agent is CrewAgentSummary => typeof agent?.agent_id === 'string')
        : [];

      crewDetails = {
        ...details,
        agents
      };
      lastLoadedCrewId = crewId;
      loopAgentSequence = agents.map((agent) => agent.agent_id);
      initializeAgentPrompts(loopAgentSequence);
      resetQuestion();
    } catch (error) {
      if (currentRequest !== detailsRequestId) {
        return;
      }
      console.error('Failed to load crew details', error);
      crewDetails = null;
      loopAgentSequence = [];
      initializeAgentPrompts([]);
      crewDetailsError = extractErrorMessage(
        error,
        'Unable to load crew details. Please try again.'
      );
      lastLoadedCrewId = crewId;
      resetQuestion();
    } finally {
      if (currentRequest === detailsRequestId) {
        crewDetailsLoading = false;
        pendingCrewId = null;
      }
    }
  }

  async function handleSubmit(event: Event) {
    event.preventDefault();
    jobError = '';

    if (!selectedCrewId) {
      jobError = 'Please choose a crew to ask your question.';
      return;
    }

    const executionOptions: crewApi.ExecuteCrewOptions = {
      execution_mode: currentMode
    };
    let queryPayload: string | Record<string, string>;

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
        const customTasks: Record<string, string> = {};
        for (const [agentId, prompt] of entries) {
          customTasks[agentId] = prompt.trim();
        }
        queryPayload = customTasks;
      }

      if (parallelSynthesisPrompt.trim()) {
        executionOptions.synthesis_prompt = parallelSynthesisPrompt.trim();
      }

      const kwargs: Record<string, unknown> = {};
      if (parallelAllResults) {
        kwargs.all_results = true;
      }
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
      const kwargs: Record<string, unknown> = {
        condition: loopCondition.trim(),
        max_iterations: iterations
      };
      if (loopAgentSequence.length) {
        kwargs.agent_sequence = [...loopAgentSequence];
      }

      if (loopSynthesisPrompt.trim()) {
        executionOptions.synthesis_prompt = loopSynthesisPrompt.trim();
      }

      executionOptions.kwargs = kwargs;
    } else if (currentMode === 'flow') {
      if (!flowInitialTask.trim()) {
        jobError = 'Please provide an initial task for the flow execution.';
        return;
      }

      queryPayload = flowInitialTask.trim();

      if (flowSynthesisPrompt.trim()) {
        executionOptions.synthesis_prompt = flowSynthesisPrompt.trim();
      }
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

      if (!execution?.job_id) {
        throw new Error('The crew execution did not return a job identifier.');
      }

      const finalStatus = await crewApi.pollJobUntilComplete(execution.job_id, 2000, 120);
      jobStatus = finalStatus as CrewJobStatus;
      statusMessage = finalStatus?.message ?? `Crew status: ${finalStatus?.status ?? 'unknown'}`;
    } catch (error) {
      console.error('Failed to execute crew', error);
      jobError = extractErrorMessage(error, 'Unable to execute the crew. Please try again.');
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

  function handleModeChange(mode: CrewExecutionMode) {
    if (currentMode !== mode) {
      currentMode = mode;
    }
    modeLocked = true;
    jobStatus = null;
    jobError = '';
    statusMessage = '';
  }

  function retryLoadCrewDetails() {
    if (!selectedCrewId) {
      return;
    }
    lastLoadedCrewId = null;
    pendingCrewId = null;
    void loadCrewDetails(selectedCrewId);
  }

  onMount(() => {
    const initialCrewId = get(page).url.searchParams.get('crew_id');
    fetchCrews(initialCrewId);
  });
</script>

<svelte:head>
  <title>Ask a Crew</title>
</svelte:head>

<div class="min-h-screen bg-base-200/60 py-10">
  <div class="mx-auto max-w-5xl space-y-8 px-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-3xl font-bold text-base-content">Ask a Crew</h1>
        <p class="mt-2 text-base text-base-content/70">
          Select one of your existing crews and configure how it should run. Provide prompts, loop conditions, or
          synthesis instructions and review both the final outcome and each agent's contribution.
        </p>
      </div>
      <a class="btn btn-ghost" href="/">
        ← Back to dashboard
      </a>
    </div>

    <section class="rounded-xl bg-base-100 p-6 shadow">
      <form class="space-y-6" on:submit={handleSubmit}>
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-base-content/80" for={crewSelectId}>Select crew</label>
          {#if crewsLoading}
            <div class="flex items-center gap-3 rounded-lg border border-dashed border-base-300 p-4 text-sm text-base-content/70">
              <LoadingSpinner size="sm" center={false} />
              <span>Loading crews…</span>
            </div>
          {:else if crewsError}
            <div class="alert alert-error">
              <span>{crewsError}</span>
              <button type="button" class="btn btn-sm" on:click={() => fetchCrews(selectedCrewId)}>
                Retry
              </button>
            </div>
          {:else}
            <select
              class="select select-bordered w-full"
              id={crewSelectId}
              bind:value={selectedCrewId}
            >
              <option value="" disabled selected={!selectedCrewId}>
                Choose a crew to query
              </option>
              {#each crews as crewItem (crewItem.crew_id)}
                <option value={crewItem.crew_id}>
                  {crewItem.name} — {crewItem.crew_id}
                </option>
              {/each}
            </select>
            {#if selectedCrew}
              <div class="space-y-2 text-sm text-base-content/70">
                <p>
                  <span class="font-semibold">Crew ID:</span> {selectedCrew.crew_id}
                  <span class="mx-2">·</span>
                  <span class="font-semibold">Default mode:</span> {selectedCrew.execution_mode || 'sequential'}
                </p>
                <p class="text-xs text-base-content/60">
                  {selectedCrew.description || 'No description provided'}
                </p>
                {#if crewDetails?.agents}
                  <p class="text-xs text-base-content/60">
                    <span class="font-semibold text-base-content">Agents:</span> {crewDetails.agents.length}
                  </p>
                {/if}
              </div>
            {/if}
            {#if crewDetailsLoading}
              <div class="mt-3 flex items-center gap-3 rounded-lg border border-dashed border-base-300 p-3 text-sm text-base-content/70">
                <LoadingSpinner size="sm" center={false} />
                <span>Loading crew details…</span>
              </div>
            {:else if crewDetailsError}
              <div class="alert alert-warning mt-3">
                <span>{crewDetailsError}</span>
                <button type="button" class="btn btn-sm" on:click={retryLoadCrewDetails}>
                  Retry
                </button>
              </div>
            {/if}
          {/if}
        </div>

        {#if selectedCrew}
          <div class="rounded-lg border border-base-300 bg-base-200/60 px-4 py-4 text-sm text-base-content/70">
            <div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div class="space-y-1">
                <span class="block text-sm font-semibold uppercase tracking-wide text-base-content/80">
                  Execution mode
                </span>
                <p class="text-xs text-base-content/60">
                  {executionModeMeta[currentMode].description}
                </p>
              </div>
              <div class="w-full max-w-xs">
                <label class="form-control w-full">
                  <span class="label-text text-xs font-semibold text-base-content/60">Mode</span>
                  <select
                    class="select select-bordered mt-1 w-full capitalize"
                    bind:value={currentMode}
                    on:change={(event) =>
                      handleModeChange((event.target as HTMLSelectElement).value as CrewExecutionMode)
                    }
                    disabled={isSubmitting || crewsLoading || crewDetailsLoading}
                  >
                    {#each executionModeOptions as option (option.value)}
                      <option value={option.value} class="capitalize">{option.label}</option>
                    {/each}
                  </select>
                </label>
              </div>
            </div>
            {#if crewDetails?.agents}
              <p class="mt-4 text-xs text-base-content/60">
                <span class="font-semibold text-base-content">Agents:</span> {crewDetails.agents.length}
              </p>
            {/if}
          </div>
        {/if}

        {#if currentMode === 'parallel'}
          <div class="space-y-6">
            <div class="rounded-lg border border-base-300 bg-base-100 p-4">
              <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 class="text-lg font-semibold text-base-content">Parallel tasks</h3>
                  <p class="text-sm text-base-content/70">Choose how prompts are distributed across agents.</p>
                </div>
              </div>
              <div class="mt-4 flex flex-col gap-2 md:flex-row md:items-center">
                <label class="flex cursor-pointer items-center gap-2 rounded-lg border border-base-300 bg-base-200/60 px-3 py-2 text-sm">
                  <input
                    type="radio"
                    class="radio radio-sm"
                    value="shared"
                    bind:group={parallelInputMode}
                    disabled={isSubmitting || crewDetailsLoading}
                  />
                  <span>Single prompt for all agents</span>
                </label>
                <label class="flex cursor-pointer items-center gap-2 rounded-lg border border-base-300 bg-base-200/60 px-3 py-2 text-sm">
                  <input
                    type="radio"
                    class="radio radio-sm"
                    value="custom"
                    bind:group={parallelInputMode}
                    disabled={isSubmitting || crewDetailsLoading || !(crewDetails?.agents?.length)}
                  />
                  <span>Custom prompt per agent</span>
                </label>
              </div>
              {#if parallelInputMode === 'shared'}
                <div class="mt-4">
                  <MarkdownEditor
                    bind:value={parallelSharedTask}
                    helperText="This prompt will be sent to every agent."
                    disabled={isSubmitting || crewsLoading || crewDetailsLoading}
                  />
                </div>
              {:else}
                <div class="mt-4 space-y-4">
                  {#if crewDetailsLoading}
                    <div class="flex items-center gap-3 text-sm text-base-content/70">
                      <LoadingSpinner size="sm" center={false} />
                      <span>Loading agent details…</span>
                    </div>
                  {:else if crewDetailsError}
                    <p class="text-sm text-error">Crew details are unavailable. Retry loading above.</p>
                  {:else if !crewDetails?.agents?.length}
                    <p class="text-sm text-base-content/60">This crew does not have any agents configured.</p>
                  {:else}
                    {#each crewDetails.agents as agent (agent.agent_id)}
                      <div class="space-y-2 rounded-lg border border-base-300 bg-base-200/60 p-3">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                          <span class="font-semibold text-base-content">{agent.name?.trim() || agent.agent_id}</span>
                          <span class="badge badge-outline text-xs">{agent.agent_id}</span>
                        </div>
                        <textarea
                          class="textarea textarea-bordered w-full text-sm"
                          rows="3"
                          value={parallelAgentTasks[agent.agent_id] ?? ''}
                          on:input={(event) =>
                            setParallelAgentTask(agent.agent_id, (event.currentTarget as HTMLTextAreaElement).value)
                          }
                          placeholder="Enter a prompt for this agent"
                          disabled={isSubmitting}
                        ></textarea>
                      </div>
                    {/each}
                  {/if}
                </div>
              {/if}
            </div>

            <div class="rounded-lg border border-base-300 bg-base-100 p-4">
              <h3 class="text-lg font-semibold text-base-content">Synthesis</h3>
              <p class="text-sm text-base-content/70">
                Provide an optional synthesis prompt to summarize the combined results.
              </p>
              <textarea
                class="textarea textarea-bordered mt-3 w-full text-sm"
                rows="3"
                bind:value={parallelSynthesisPrompt}
                placeholder="Ask the crew to synthesize the parallel outputs (optional)"
                disabled={isSubmitting}
              ></textarea>
              <label class="mt-4 flex items-center justify-between gap-3 rounded-lg border border-base-300 bg-base-200/60 px-4 py-3 text-sm text-base-content">
                <span>Return each agent result separately</span>
                <input type="checkbox" class="toggle" bind:checked={parallelAllResults} disabled={isSubmitting} />
              </label>
              <p class="mt-2 text-xs text-base-content/60">
                When enabled, the final output will be a list of each agent&apos;s response.
              </p>
            </div>
          </div>
        {:else if currentMode === 'loop'}
          <div class="space-y-6">
            <div class="space-y-4 rounded-lg border border-base-300 bg-base-100 p-4">
              <div>
                <h3 class="text-lg font-semibold text-base-content">Loop configuration</h3>
                <p class="text-sm text-base-content/70">
                  Provide the initial task and stopping criteria for the loop.
                </p>
              </div>
              <MarkdownEditor
                bind:value={loopInitialTask}
                helperText="Initial task for the first iteration."
                disabled={isSubmitting || crewsLoading || crewDetailsLoading}
              />
              <div class="grid gap-4 md:grid-cols-2">
                <label class="form-control w-full">
                  <span class="label-text text-sm font-semibold text-base-content">Stopping condition</span>
                  <input
                    type="text"
                    class="input input-bordered mt-2"
                    bind:value={loopCondition}
                    placeholder="Stop when..."
                    disabled={isSubmitting}
                  />
                  <span class="mt-1 text-xs text-base-content/60">
                    Example: “Stop when the reviewer marks the report as FINAL”.
                  </span>
                </label>
                <label class="form-control w-full">
                  <span class="label-text text-sm font-semibold text-base-content">Max iterations</span>
                  <input
                    type="number"
                    class="input input-bordered mt-2"
                    min="1"
                    bind:value={loopMaxIterations}
                    disabled={isSubmitting}
                  />
                  <span class="mt-1 text-xs text-base-content/60">
                    Safety limit for how many times the loop can run.
                  </span>
                </label>
              </div>
            </div>

            <div class="space-y-3 rounded-lg border border-base-300 bg-base-100 p-4">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 class="text-lg font-semibold text-base-content">Agent sequence</h3>
                <span class="text-xs text-base-content/60">Drag and drop to reorder</span>
              </div>
              {#if crewDetailsLoading}
                <div class="flex items-center gap-3 text-sm text-base-content/70">
                  <LoadingSpinner size="sm" center={false} />
                  <span>Loading agents…</span>
                </div>
              {:else if !loopAgentSequence.length}
                <p class="text-sm text-base-content/60">No agents available for loop execution.</p>
              {:else}
                <ul class="space-y-2">
                  {#each loopAgentSequence as agentId, index (agentId)}
                    <li
                      class:opacity-60={draggingIndex === index}
                      class="flex items-center justify-between gap-3 rounded-lg border border-base-300 bg-base-100 p-3"
                      draggable={!isSubmitting}
                      on:dragstart={(event) => handleDragStart(event, index)}
                      on:dragover={handleDragOver}
                      on:drop={(event) => handleDrop(event, index)}
                      on:dragend={handleDragEnd}
                    >
                      <div>
                        <p class="font-semibold text-base-content">{getAgentDisplayName(agentId)}</p>
                        <p class="text-xs text-base-content/60">{agentId}</p>
                      </div>
                      <div class="flex items-center gap-2">
                        <button
                          type="button"
                          class="btn btn-ghost btn-xs"
                          on:click={() => moveAgentUp(index)}
                          disabled={index === 0 || isSubmitting}
                          aria-label={`Move ${getAgentDisplayName(agentId)} up`}
                          title="Move up"
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          class="btn btn-ghost btn-xs"
                          on:click={() => moveAgentDown(index)}
                          disabled={index === loopAgentSequence.length - 1 || isSubmitting}
                          aria-label={`Move ${getAgentDisplayName(agentId)} down`}
                          title="Move down"
                        >
                          ↓
                        </button>
                      </div>
                    </li>
                  {/each}
                </ul>
                <div
                  class="rounded-lg border border-dashed border-base-300 bg-base-200/60 p-3 text-center text-xs text-base-content/60"
                  on:dragover={handleDragOver}
                  on:drop={handleDropAtEnd}
                >
                  Drop here to move an agent to the end of the sequence
                </div>
              {/if}
            </div>

            <div class="rounded-lg border border-base-300 bg-base-100 p-4">
              <h3 class="text-lg font-semibold text-base-content">Synthesis</h3>
              <p class="text-sm text-base-content/70">
                Optionally summarize the loop results after the stopping condition is met.
              </p>
              <textarea
                class="textarea textarea-bordered mt-3 w-full text-sm"
                rows="3"
                bind:value={loopSynthesisPrompt}
                placeholder="Ask the crew to synthesize the loop outputs (optional)"
                disabled={isSubmitting}
              ></textarea>
            </div>
          </div>
        {:else if currentMode === 'flow'}
          <div class="space-y-6">
            <div class="space-y-4 rounded-lg border border-base-300 bg-base-100 p-4">
              <div>
                <h3 class="text-lg font-semibold text-base-content">Flow execution</h3>
                <p class="text-sm text-base-content/70">
                  Provide the starting task for the workflow defined in the crew builder.
                </p>
              </div>
              <MarkdownEditor
                bind:value={flowInitialTask}
                helperText="Initial task for the flow execution."
                disabled={isSubmitting || crewsLoading || crewDetailsLoading}
              />
              <p class="text-xs text-base-content/60">
                The execution order follows the flow configuration from the crew builder.
              </p>
            </div>

            <div class="rounded-lg border border-base-300 bg-base-100 p-4">
              <h3 class="text-lg font-semibold text-base-content">Synthesis</h3>
              <p class="text-sm text-base-content/70">
                Optionally summarize results from the completed flow.
              </p>
              <textarea
                class="textarea textarea-bordered mt-3 w-full text-sm"
                rows="3"
                bind:value={flowSynthesisPrompt}
                placeholder="Ask the crew to synthesize the flow outputs (optional)"
                disabled={isSubmitting}
              ></textarea>
            </div>
          </div>
        {:else}
          <MarkdownEditor
            bind:value={question}
            helperText="Supports headings, lists, inline code, and more."
            disabled={isSubmitting || crewsLoading}
          />
        {/if}

        {#if jobError}
          <div class="alert alert-error">
            <span>{jobError}</span>
          </div>
        {/if}

        <div class="flex flex-wrap gap-3">
          <button type="submit" class="btn btn-primary" disabled={isSubmitting || !selectedCrewId}>
            {#if isSubmitting}
              <span class="loading loading-spinner"></span>
              Running…
            {:else}
              Ask Crew
            {/if}
          </button>
          <button type="button" class="btn btn-ghost" on:click={resetQuestion} disabled={isSubmitting}>
            Clear
          </button>
        </div>
      </form>
    </section>

    {#if isSubmitting}
      <div class="flex items-center justify-center gap-3 rounded-xl border border-dashed border-base-300 bg-base-100 p-6 text-base-content/70">
        <LoadingSpinner text="Waiting for the crew to finish…" />
      </div>
    {/if}

    {#if statusMessage}
      <div class="alert alert-info">
        <div>
          <span class="font-semibold">Status:</span>
          <span class="ml-2">{statusMessage}</span>
        </div>
        {#if jobStatus}
          <span class="badge badge-outline">{jobStatus.status}</span>
        {/if}
      </div>
    {/if}

    {#if jobStatus}
      <section class="space-y-6">
        <div class="rounded-xl bg-base-100 p-6 shadow">
          <div class="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 class="text-2xl font-semibold text-base-content">Crew response</h2>
              <p class="text-sm text-base-content/70">Job ID: {jobStatus.job_id}</p>
              {#if jobStatus.execution_mode}
                <p class="text-sm text-base-content/60">
                  Execution mode: {getExecutionModeLabel(jobStatus.execution_mode)}
                </p>
              {/if}
            </div>
            <div class="badge badge-primary badge-outline text-base-content">
              {jobStatus.status}
            </div>
          </div>

          <div class="mt-6 space-y-4">
            <div class="rounded-lg border border-base-300 bg-base-200 p-4">
              <h3 class="text-lg font-semibold text-base-content">Final output</h3>
              {#if finalOutputHtml}
                <div class="mt-3 space-y-2 text-base leading-relaxed text-base-content">
                  {@html finalOutputHtml}
                </div>
              {:else if finalOutputList.length}
                <div class="mt-3 space-y-3">
                  {#each finalOutputList as item, index (index)}
                    <div class="rounded-lg border border-base-300 bg-base-100 p-3">
                      <div class="text-sm font-semibold text-base-content">Result {index + 1}</div>
                      {#if finalOutputListHtml[index]}
                        <div class="mt-2 space-y-2 text-sm leading-relaxed text-base-content">
                          {@html finalOutputListHtml[index]}
                        </div>
                      {:else}
                        <p class="mt-2 text-sm text-base-content/70">{String(item ?? '')}</p>
                      {/if}
                    </div>
                  {/each}
                </div>
              {:else}
                <p class="mt-3 text-base-content/70">No final output was returned.</p>
              {/if}
            </div>

            {#if agentResponses.length}
              <div class="rounded-lg border border-base-300 bg-base-200 p-4">
                <h3 class="text-lg font-semibold text-base-content">Agents responses</h3>
                <div class="mt-4 space-y-4">
                  {#each agentResponses as agent (agent.name)}
                    <div class="rounded-lg border border-base-300 bg-base-100 p-4">
                      <h4 class="text-base font-semibold text-base-content">{agent.name}</h4>
                      {#if agent.input}
                        <p class="mt-2 text-sm text-base-content/70">
                          <span class="font-semibold">Input:</span> {agent.input}
                        </p>
                      {/if}
                      {#if agent.outputHtml}
                        <div class="mt-3 space-y-2 text-sm leading-relaxed text-base-content">
                          {@html agent.outputHtml}
                        </div>
                      {:else}
                        <p class="mt-3 text-sm text-base-content/60">No output recorded for this agent.</p>
                      {/if}
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        </div>

        <JsonViewer data={jobStatus} title="Advanced results" />
      </section>
    {/if}
  </div>
</div>
