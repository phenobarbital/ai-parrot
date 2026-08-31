<script lang="ts">
  import Icon from '@iconify/svelte';
  import { toggleDataset, deleteDataset } from '$lib/api/agent';
  import type { DatasetEntry } from '$lib/types/dataset';
  import { toastStore } from '$lib/stores/toast.svelte';
  import DatasetInlinePreview from './DatasetInlinePreview.svelte';

  let {
    agentId,
    datasets = $bindable([]),
    onPreview,
  }: {
    agentId: string;
    datasets: DatasetEntry[];
    /** @deprecated Preview is now inline — this prop is ignored */
    onPreview?: (dataset: DatasetEntry) => void;
  } = $props();

  let toggling = $state<Set<string>>(new Set());
  let pendingDelete = $state<string | null>(null);
  let deleting = $state(false);
  let selectedDataset = $state<DatasetEntry | null>(null);

  let activeCount = $derived(datasets.filter((d) => d.is_active).length);

  // Auto-select first dataset on load
  $effect(() => {
    if (datasets.length > 0 && !selectedDataset) {
      selectedDataset = datasets[0];
    }
  });

  async function handleToggle(dataset: DatasetEntry) {
    if (toggling.has(dataset.name)) return;
    const next = new Set(toggling);
    next.add(dataset.name);
    toggling = next;

    const original = dataset.is_active;
    // Use non-mutating update for Svelte 5 reactivity
    datasets = datasets.map(d =>
      d.name === dataset.name ? { ...d, is_active: !original } : d
    );

    try {
      await toggleDataset(agentId, dataset.name, !original);
    } catch {
      datasets = datasets.map(d =>
        d.name === dataset.name ? { ...d, is_active: original } : d
      );
      toastStore.error(`Failed to update "${dataset.name}"`);
    } finally {
      const after = new Set(toggling);
      after.delete(dataset.name);
      toggling = after;
    }
  }

  async function handleDelete(name: string) {
    deleting = true;
    try {
      await deleteDataset(agentId, name);
      datasets = datasets.filter((d) => d.name !== name);
      pendingDelete = null;
      // If the deleted dataset was selected, clear or select next
      if (selectedDataset?.name === name) {
        selectedDataset = datasets.length > 0 ? datasets[0] : null;
      }
    } catch {
      toastStore.error(`Failed to delete "${name}"`);
    } finally {
      deleting = false;
    }
  }
</script>

<div class="flex h-full min-h-[400px]">
  <!-- Left panel: dataset list -->
  <div class="w-[280px] shrink-0 border-r border-slate-200 dark:border-slate-700 overflow-y-auto flex flex-col">
    <!-- Header summary -->
    {#if datasets.length > 0}
      <p class="text-xs text-slate-500 dark:text-slate-400 px-3 pt-3 pb-1 shrink-0">
        {datasets.length} dataset{datasets.length !== 1 ? 's' : ''} · {activeCount} active
      </p>
    {/if}

    <!-- Dataset rows -->
    <div class="flex flex-col gap-1 p-2 flex-1">
      {#each datasets as dataset (dataset.name)}
        <div
          class="rounded-lg border transition-colors cursor-pointer
            {selectedDataset?.name === dataset.name
              ? 'border-primary-400 dark:border-primary-600 bg-primary-50 dark:bg-primary-900/20'
              : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600'}"
          onclick={() => { if (pendingDelete !== dataset.name) selectedDataset = dataset; }}
          role="button"
          tabindex="0"
          onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectedDataset = dataset; } }}
          aria-label="Select {dataset.name}"
        >
          <!-- Main row -->
          <div class="flex items-center gap-2 px-2.5 py-2">
            <!-- Toggle checkbox -->
            <input
              type="checkbox"
              class="checkbox checkbox-sm shrink-0"
              checked={dataset.is_active}
              disabled={toggling.has(dataset.name)}
              onchange={(e) => { e.stopPropagation(); handleToggle(dataset); }}
              onclick={(e) => e.stopPropagation()}
              aria-label="Enable {dataset.name}"
            />

            <!-- Name + meta -->
            <div class="flex flex-col min-w-0 flex-1">
              <div class="flex items-center gap-1 min-w-0">
                <span
                  class="text-xs font-medium truncate {dataset.is_active
                    ? 'text-slate-800 dark:text-slate-100'
                    : 'text-slate-400 dark:text-slate-500'}"
                >
                  {dataset.name}
                </span>
                {#if dataset.source_type}
                  <span
                    class="inline-flex items-center shrink-0 px-1 py-0.5 text-[9px] font-medium rounded
                      bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400"
                  >
                    {dataset.source_type}
                  </span>
                {/if}
              </div>
              {#if dataset.description}
                <span class="text-[10px] text-slate-400 dark:text-slate-500 truncate leading-tight">
                  {dataset.description.slice(0, 50)}{dataset.description.length > 50 ? '...' : ''}
                </span>
              {/if}
              <span class="text-[10px] text-slate-400 dark:text-slate-500">
                {#if dataset.shape}
                  {dataset.shape[0].toLocaleString()} × {dataset.shape[1]}
                {/if}
                {#if !dataset.loaded}
                  <span class="text-amber-500 dark:text-amber-400">(not loaded)</span>
                {/if}
              </span>
            </div>

            <!-- Delete button -->
            <button
              class="btn btn-ghost btn-xs shrink-0"
              onclick={(e) => { e.stopPropagation(); pendingDelete = dataset.name; }}
              title="Delete dataset"
              aria-label="Delete {dataset.name}"
            >
              <Icon icon="mdi:trash-can-outline" class="h-3.5 w-3.5 text-red-400 dark:text-red-500" />
            </button>
          </div>

          <!-- Inline delete confirmation -->
          {#if pendingDelete === dataset.name}
            <div class="border-t border-slate-100 dark:border-slate-700 px-2.5 py-2 bg-red-50 dark:bg-red-950/30 flex items-center justify-between gap-1">
              <span class="text-[10px] text-red-700 dark:text-red-400">
                Delete <strong>{dataset.name}</strong>?
              </span>
              <div class="flex gap-1 shrink-0">
                <button
                  class="btn btn-xs btn-ghost"
                  onclick={(e) => { e.stopPropagation(); pendingDelete = null; }}
                  disabled={deleting}
                >
                  Cancel
                </button>
                <button
                  class="btn btn-xs btn-error"
                  onclick={(e) => { e.stopPropagation(); handleDelete(dataset.name); }}
                  disabled={deleting}
                >
                  {deleting ? '...' : 'Delete'}
                </button>
              </div>
            </div>
          {/if}
        </div>
      {/each}

      <!-- Empty state -->
      {#if datasets.length === 0}
        <div
          class="flex flex-col items-center justify-center py-12 text-gray-400 dark:text-gray-500 gap-3 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-lg flex-1"
        >
          <Icon icon="mdi:database-off" class="h-8 w-8" />
          <p class="text-xs">No datasets available</p>
          <p class="text-[10px] text-center px-4">
            Use the "Add Dataset" tab to upload a file or add a SQL query.
          </p>
        </div>
      {/if}
    </div>
  </div>

  <!-- Right panel: inline preview -->
  <div class="flex-1 overflow-hidden">
    {#if selectedDataset}
      <DatasetInlinePreview {agentId} dataset={selectedDataset} />
    {:else}
      <div class="flex items-center justify-center h-full text-slate-400 dark:text-slate-500">
        <div class="flex flex-col items-center gap-2">
          <Icon icon="mdi:cursor-default-click-outline" class="h-10 w-10" />
          <span class="text-sm">Select a dataset to preview</span>
        </div>
      </div>
    {/if}
  </div>
</div>
