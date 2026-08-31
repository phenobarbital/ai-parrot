<script lang="ts">
  import { AppDialog } from '$lib/ui/components';
  import Icon from '@iconify/svelte';
  import { listDatasets } from '$lib/api/agent';
  import type { DatasetEntry, DatasetAddResponse } from '$lib/types/dataset';
  import DatasetTab from './DatasetTab.svelte';
  import DatasetCreatePane from './DatasetCreatePane.svelte';

  let {
    open = $bindable(false),
    agentId,
  }: {
    open: boolean;
    agentId: string;
  } = $props();

  let activeTab = $state<'list' | 'create'>('list');
  let datasets = $state<DatasetEntry[]>([]);
  let loading = $state(false);
  let fetchError = $state('');

  $effect(() => {
    if (open) {
      activeTab = 'list';
      fetchDatasets();
    }
  });

  async function fetchDatasets() {
    loading = true;
    fetchError = '';
    try {
      const result = await listDatasets(agentId);
      datasets = result.datasets;
    } catch {
      fetchError = 'Failed to load datasets. Please try again.';
    } finally {
      loading = false;
    }
  }

  function handleCreated(result: DatasetAddResponse) {
    if (result.shape) {
      // Legacy response (slug/sql/file) — normalize to DatasetEntry before appending
      const entry: DatasetEntry = {
        name: result.name,
        description: result.description ?? '',
        shape: result.shape,
        is_active: result.is_active ?? true,
        loaded: result.loaded ?? false,
        source_type: result.type,
      };
      datasets = [...datasets, entry];
    } else {
      // Datasource response (table/smartsheet) — refetch to get current state
      fetchDatasets();
    }
    activeTab = 'list';
  }
</script>

<AppDialog bind:open title="Dataset Configuration" size="3xl">
  <div class="h-[63vh] flex flex-col overflow-hidden">
    <!-- Tab toggle -->
    <div class="flex gap-1 p-1 bg-gray-100 dark:bg-gray-800 rounded-lg w-fit mb-4 shrink-0">
      <button
        type="button"
        class="px-3 py-1.5 text-sm rounded-md transition-colors {activeTab === 'list'
          ? 'bg-white dark:bg-gray-700 shadow-sm font-medium text-gray-900 dark:text-gray-100'
          : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
        onclick={() => (activeTab = 'list')}
      >
        List
      </button>
      <button
        type="button"
        class="px-3 py-1.5 text-sm rounded-md transition-colors {activeTab === 'create'
          ? 'bg-white dark:bg-gray-700 shadow-sm font-medium text-gray-900 dark:text-gray-100'
          : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
        onclick={() => (activeTab = 'create')}
      >
        Add Dataset
      </button>
    </div>

    <!-- Content area -->
    <div class="flex-1 overflow-hidden">
      {#if activeTab === 'create'}
        <DatasetCreatePane {agentId} onCreated={handleCreated} />
      {:else if loading}
        <!-- Skeleton rows -->
        <div class="flex flex-col gap-2">
          {#each [1, 2, 3] as _}
            <div class="h-14 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse"></div>
          {/each}
        </div>

      {:else if fetchError}
        <div class="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 py-4">
          <Icon icon="mdi:alert-circle" class="h-5 w-5 shrink-0" />
          <span>{fetchError}</span>
          <button class="underline ml-2 hover:no-underline" onclick={fetchDatasets}>Retry</button>
        </div>

      {:else}
        <DatasetTab {agentId} bind:datasets />
      {/if}
    </div>
  </div>

  {#snippet footer()}
    <div class="flex justify-end">
      <button class="btn btn-ghost" onclick={() => (open = false)}>Close</button>
    </div>
  {/snippet}
</AppDialog>
