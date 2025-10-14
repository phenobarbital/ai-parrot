<script lang="ts">
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { crew as crewApi } from '$lib/api';
  import ThemeToggle from '$lib/components/ThemeToggle.svelte';
  import { crewStore } from '$lib/stores/crewStore';

  const dispatch = createEventDispatcher();

  let crewName = '';
  let crewDescription = '';
  let executionMode: 'sequential' | 'parallel' | 'hierarchical' = 'sequential';
  let uploading = false;
  let uploadStatus: { type: 'success' | 'error'; message: string } | null = null;

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

  async function uploadToAPI() {
    try {
      uploading = true;
      uploadStatus = null;
      const crewJSON = crewStore.exportToJSON();
      const response = await crewApi.createCrew(crewJSON);
      uploadStatus = {
        type: 'success',
        message: `Crew "${response.name ?? crewJSON.name}" created successfully!`
      };
      window.setTimeout(() => {
        uploadStatus = null;
      }, 3000);
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
    <div class="flex items-center gap-2 text-xl font-semibold">
      <span class="text-2xl">🦜</span>
      <span>AgentCrew Builder</span>
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
    <button class="btn btn-primary btn-sm" type="button" onclick={() => dispatch('addAgent')}>
      + Agent
    </button>
    <button class="btn btn-success btn-sm" type="button" onclick={uploadToAPI} disabled={uploading}>
      {uploading ? 'Uploading…' : 'Upload'}
    </button>
    <button class="btn btn-info btn-sm" type="button" onclick={() => dispatch('export')}>
      Export JSON
    </button>
  </div>
</div>

{#if uploadStatus}
  <div class={`alert fixed right-4 top-24 z-50 max-w-sm shadow-lg ${uploadStatus.type === 'success' ? 'alert-success' : 'alert-error'}`}>
    <span>{uploadStatus.message}</span>
  </div>
{/if}
