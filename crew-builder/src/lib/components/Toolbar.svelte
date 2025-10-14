<script lang="ts">
  import { onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { crew as crewApi } from '$lib/api';
  import ThemeToggle from '$lib/components/ThemeToggle.svelte';
  import { crewStore } from '$lib/stores/crewStore';
  import { toastStore } from '$lib/stores/toast.svelte';

  // Svelte 5: Use callback props instead of createEventDispatcher
  interface Props {
    onAddAgent?: () => void;
    onExport?: () => void;
  }

  let { onAddAgent, onExport }: Props = $props();

  let crewName = $state('');
  let crewDescription = $state('');
  let executionMode = $state<'sequential' | 'parallel' | 'hierarchical'>('sequential');
  let uploading = $state(false);
  let uploadStatus = $state<{ type: 'success' | 'error'; message: string } | null>(null);

  const unsubscribe = crewStore.subscribe((value) => {
    crewName = value.metadata.name;
    crewDescription = value.metadata.description;
    executionMode = value.metadata.execution_mode;
  });

  onDestroy(() => {
    unsubscribe();
  });

  function updateMetadata() {
    crewStore.updateMetadata({
      name: crewName,
      description: crewDescription,
      execution_mode: executionMode
    });
  }

  function goHome() {
    crewStore.reset();
    goto('/');
  }

  async function uploadToAPI() {
    try {
      uploading = true;
      const crewJSON = crewStore.exportToJSON();
      const response = await crewApi.createCrew(crewJSON);
      toastStore.success(`Crew "${response.name ?? crewJSON.name}" created successfully!`);
    } catch (error) {
      const responseMessage =
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        typeof (error as { response?: { data?: { message?: string } } }).response?.data?.message === 'string'
          ? (error as { response?: { data?: { message?: string } } }).response?.data?.message
          : undefined;
      const fallbackMessage =
        error instanceof Error && typeof error.message === 'string'
          ? error.message
          : 'Failed to upload crew';
      const message = responseMessage ?? fallbackMessage;
      uploadStatus = {
        type: 'error',
        message
      };
    } finally {
      uploading = false;
    }
  }
</script>

<div class="navbar border-b border-base-300 bg-base-100 px-4 shadow-sm">
  <div class="flex flex-1 items-center gap-4">
    <!-- Home Button -->
    <button
      class="btn btn-ghost btn-sm gap-2"
      onclick={goHome}
      aria-label="Go to home"
      type="button"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        class="h-5 w-5"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
        />
      </svg>
      <span class="hidden sm:inline">Home</span>
    </button>

    <div class="flex items-center gap-2 text-xl font-semibold">
      <span class="text-2xl">🦜</span>
      <span class="hidden sm:inline">AgentCrew Builder</span>
      <span class="sm:hidden">Builder</span>
    </div>

    <div class="flex flex-1 flex-wrap items-center gap-3">
      <label class="form-control w-full max-w-xs">
        <span class="label-text">Crew name</span>
        <input
          class="input input-bordered input-sm"
          type="text"
          bind:value={crewName}
          onchange={updateMetadata}
          placeholder="Crew name..."
        />
      </label>
      <label class="form-control w-full max-w-sm">
        <span class="label-text">Description</span>
        <input
          class="input input-bordered input-sm"
          type="text"
          bind:value={crewDescription}
          onchange={updateMetadata}
          placeholder="Description..."
        />
      </label>
      <label class="form-control w-full max-w-[160px]">
        <span class="label-text">Execution mode</span>
        <select class="select select-bordered select-sm" bind:value={executionMode} onchange={updateMetadata}>
          <option value="sequential">Sequential</option>
          <option value="parallel">Parallel (Coming Soon)</option>
          <option value="hierarchical">Hierarchical (Coming Soon)</option>
        </select>
      </label>
    </div>
  </div>

  <div class="flex items-center gap-2">
    <ThemeToggle />
    <button class="btn btn-primary btn-sm" type="button" onclick={() => onAddAgent?.()}>
      + Agent
    </button>
    <button class="btn btn-success btn-sm" type="button" onclick={uploadToAPI} disabled={uploading}>
      {uploading ? 'Uploading…' : 'Upload'}
    </button>
    <button class="btn btn-info btn-sm" type="button" onclick={() => onExport?.()}>
      Export JSON
    </button>
  </div>
</div>

{#if uploadStatus}
  <div class={`alert fixed right-4 top-24 z-50 max-w-sm shadow-lg ${uploadStatus.type === 'success' ? 'alert-success' : 'alert-error'}`}>
    <span>{uploadStatus.message}</span>
  </div>
{/if}
