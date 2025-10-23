<script lang="ts" context="module">
  export const ssr = false;
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { page } from '$app/stores';
  import { crew as crewApi } from '$lib/api';
  import MarkdownEditor from '$lib/components/MarkdownEditor.svelte';
  import JsonViewer from '$lib/components/JsonViewer.svelte';
  import { markdownToHtml } from '$lib/utils/markdown';
  import { LoadingSpinner } from '../../../components';

  interface CrewSummary {
    crew_id: string;
    name: string;
    description?: string;
    execution_mode?: string;
  }

  interface CrewJobStatus {
    job_id: string;
    crew_id: string;
    status: string;
    message?: string;
    result?: {
      output?: string;
      response?: Record<string, { input?: string; output?: string }>;
    };
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
  let question = '';
  let jobStatus: CrewJobStatus | null = null;
  let statusMessage = '';
  let jobError = '';
  let isSubmitting = false;
  let rawAgentResponses: [string, AgentResponse][] = [];
  let agentResponses: AgentResponseView[] = [];

  $: selectedCrew = crews.find((crewItem) => crewItem.crew_id === selectedCrewId) ?? null;
  $: finalOutputHtml = jobStatus?.result?.output ? markdownToHtml(jobStatus.result.output) : '';
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

  async function fetchCrews(initialCrewId?: string | null) {
    crewsLoading = true;
    crewsError = '';

    try {
      const response = await crewApi.listCrews();
      const list = Array.isArray(response?.crews) ? (response.crews as CrewSummary[]) : [];
      crews = list;

      if (initialCrewId) {
        const exists = list.some((item) => item.crew_id === initialCrewId);
        if (exists) {
          selectedCrewId = initialCrewId;
        }
      }
    } catch (error) {
      console.error('Failed to load crews', error);
      let responseMessage: string | undefined;
      if (
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        error.response &&
        typeof error.response === 'object' &&
        'data' in error.response &&
        error.response.data &&
        typeof error.response.data === 'object' &&
        'message' in error.response.data &&
        typeof error.response.data.message === 'string'
      ) {
        responseMessage = error.response.data.message;
      }
      const fallbackMessage =
        error instanceof Error && typeof error.message === 'string'
          ? error.message
          : 'Unable to load crews at this time.';
      crewsError = responseMessage ?? fallbackMessage;
      crews = [];
    } finally {
      crewsLoading = false;
    }
  }

  async function handleSubmit(event: Event) {
    event.preventDefault();
    jobError = '';

    if (!selectedCrewId) {
      jobError = 'Please choose a crew to ask your question.';
      return;
    }

    if (!question.trim()) {
      jobError = 'Please provide a question or task for the crew.';
      return;
    }

    isSubmitting = true;
    statusMessage = '';
    jobStatus = null;

    try {
      const execution = await crewApi.executeCrew(selectedCrewId, question.trim());
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
      let responseMessage: string | undefined;
      if (
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        error.response &&
        typeof error.response === 'object' &&
        'data' in error.response &&
        error.response.data &&
        typeof error.response.data === 'object' &&
        'message' in error.response.data &&
        typeof error.response.data.message === 'string'
      ) {
        responseMessage = error.response.data.message;
      }
      const fallbackMessage =
        error instanceof Error && typeof error.message === 'string'
          ? error.message
          : 'Unable to execute the crew. Please try again.';
      jobError = responseMessage ?? fallbackMessage;
    } finally {
      isSubmitting = false;
    }
  }

  function resetQuestion() {
    question = '';
    jobStatus = null;
    jobError = '';
    statusMessage = '';
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
          Select one of your existing crews and send a Markdown-formatted question. We'll execute the crew and
          display the collective response alongside each agent's contribution.
        </p>
      </div>
      <a class="btn btn-ghost" href="/">
        ← Back to dashboard
      </a>
    </div>

    <section class="rounded-xl bg-base-100 p-6 shadow">
      <form class="space-y-6" on:submit={handleSubmit}>
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-base-content/80">Select crew</label>
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
              <div class="space-y-1 text-sm text-base-content/70">
                <p>
                  <span class="font-semibold">Crew ID:</span> {selectedCrew.crew_id}
                  <span class="mx-2">·</span>
                  <span class="font-semibold">Mode:</span> {selectedCrew.execution_mode || '—'}
                </p>
                <p class="text-xs text-base-content/60">
                  {selectedCrew.description || 'No description provided'}
                </p>
              </div>
            {/if}
          {/if}
        </div>

        <MarkdownEditor
          bind:value={question}
          helperText="Supports headings, lists, inline code, and more."
          disabled={isSubmitting || crewsLoading}
        />

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
