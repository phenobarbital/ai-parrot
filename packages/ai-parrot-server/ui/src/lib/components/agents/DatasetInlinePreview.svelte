<script lang="ts">
  import Icon from '@iconify/svelte';
  import DataTable from './DataTable.svelte';
  import http from '$lib/api/http';
  import type { DatasetEntry } from '$lib/types/dataset';

  let {
    agentId,
    dataset,
  }: {
    agentId: string;
    dataset: DatasetEntry | null;
  } = $props();

  let previewData = $state<Record<string, any>[]>([]);
  let previewColumns = $state<string[]>([]);
  let totalRows = $state(0);
  let columnMeta = $state<Record<string, { description: string; dtype: string }>>({});
  let columnTypes = $state<Record<string, string>>({});
  let edaSummary = $state<Record<string, any> | null>(null);
  let datasetDescription = $state('');
  let notLoaded = $state(false);
  let notLoadedMessage = $state('');
  let sourceType = $state('');
  let sourceDescription = $state('');
  let loading = $state(false);
  let previewUnavailable = $state(false);
  let sampleLoading = $state(false);
  let sampleFetched = $state(false);

  let hasRowData = $derived(previewData.length > 0);
  let hasColumnMeta = $derived(Object.keys(columnMeta).length > 0);

  let columnRows = $derived.by(() => {
    return Object.entries(columnMeta).map(([name, meta]) => ({
      column: name,
      description: meta.description || '—',
      dtype: meta.dtype || '—',
      type: columnTypes[name] || '—',
    }));
  });

  $effect(() => {
    // Reset and fetch metadata when dataset changes
    if (dataset) {
      previewData = [];
      previewColumns = [];
      totalRows = 0;
      columnMeta = {};
      columnTypes = {};
      edaSummary = null;
      datasetDescription = '';
      notLoaded = false;
      notLoadedMessage = '';
      sourceType = '';
      sourceDescription = '';
      previewUnavailable = false;
      sampleFetched = false;
      fetchMetadata();
    }
  });

  async function fetchMetadata() {
    loading = true;
    previewUnavailable = false;
    try {
      const { data: result } = await http.get(
        `/api/v1/agents/datasets/${agentId}/${encodeURIComponent(dataset!.name)}`,
        { params: {} }
      );

      // Extract column metadata
      if (result?.columns) {
        if (Array.isArray(result.columns)) {
          const types: Record<string, string> = result.column_types ?? {};
          const meta: Record<string, { description: string; dtype: string }> = {};
          for (const col of result.columns) {
            meta[col] = { description: '', dtype: types[col] ?? '' };
          }
          columnMeta = meta;
        } else if (typeof result.columns === 'object') {
          columnMeta = result.columns;
        }
      }
      if (result?.column_types && typeof result.column_types === 'object') {
        columnTypes = result.column_types;
      }
      if (result?.eda_summary) {
        edaSummary = result.eda_summary;
      }
      if (result?.description) {
        datasetDescription = result.description;
      }
      totalRows = result?.shape?.rows ?? dataset!.shape?.[0] ?? 0;

      // Non-loaded dataset
      if (result?.loaded === false) {
        notLoaded = true;
        notLoadedMessage = result.message ?? '';
        sourceType = result.source_type ?? '';
        sourceDescription = result.source_description ?? '';
      }
    } catch {
      previewUnavailable = true;
    } finally {
      loading = false;
    }
  }

  async function fetchSample() {
    if (!dataset || sampleLoading) return;
    sampleLoading = true;
    try {
      const { data: result } = await http.get(
        `/api/v1/agents/datasets/${agentId}/${encodeURIComponent(dataset!.name)}`,
        { params: { limit: 10 } }
      );
      if (Array.isArray(result?.data) && result.data.length > 0) {
        previewData = result.data;
        previewColumns = Array.isArray(result.columns)
          ? result.columns
          : Object.keys(result.columns ?? {});
        totalRows = result.total_rows ?? totalRows;
      }
      sampleFetched = true;
    } catch {
      // silently fail — preview table just won't show
    } finally {
      sampleLoading = false;
    }
  }

  function formatNumber(n: number): string {
    return n.toLocaleString();
  }

  function formatBytes(mb: number): string {
    if (mb < 1) return `${(mb * 1024).toFixed(0)} KB`;
    return `${mb.toFixed(2)} MB`;
  }
</script>

<div class="flex flex-col h-full overflow-hidden">
  {#if !dataset}
    <!-- No dataset selected -->
    <div class="flex-1 flex items-center justify-center text-slate-400 dark:text-slate-500">
      <div class="flex flex-col items-center gap-2">
        <Icon icon="mdi:database-off-outline" class="h-10 w-10" />
        <span class="text-sm">No dataset selected</span>
      </div>
    </div>

  {:else if loading}
    <!-- Loading metadata -->
    <div class="flex-1 flex items-center justify-center">
      <div class="flex flex-col items-center gap-3 text-slate-400">
        <span class="loading loading-spinner loading-lg"></span>
        <span class="text-sm">Loading preview...</span>
      </div>
    </div>

  {:else if previewUnavailable}
    <!-- Preview unavailable -->
    <div class="flex-1 flex items-center justify-center">
      <div class="flex flex-col items-center gap-3 text-center px-4">
        <Icon icon="mdi:eye-off" class="h-12 w-12 text-slate-300 dark:text-slate-600" />
        <div>
          <p class="text-sm font-medium text-slate-600 dark:text-slate-300">
            Preview not available
          </p>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-1">
            This dataset does not expose a preview endpoint.
          </p>
        </div>
        {#if dataset}
          <div class="text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 rounded-lg p-3 mt-1">
            <p><strong>Name:</strong> {dataset.name}</p>
            {#if dataset.shape}
              <p><strong>Rows:</strong> {dataset.shape[0].toLocaleString()}</p>
              <p><strong>Columns:</strong> {dataset.shape[1]}</p>
            {/if}
            <p><strong>Status:</strong> {dataset.is_active ? 'Active' : 'Inactive'} · {dataset.loaded ? 'Loaded' : 'Not loaded'}</p>
          </div>
        {/if}
      </div>
    </div>

  {:else}
    <!-- Content area — scrollable -->
    <div class="flex-1 overflow-y-auto flex flex-col gap-0">

      <!-- Metadata header -->
      <div class="px-4 pt-4 pb-3 shrink-0 border-b border-slate-100 dark:border-slate-800">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <h3 class="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">{dataset.name}</h3>
            {#if datasetDescription || dataset.description}
              <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
                {datasetDescription || dataset.description}
              </p>
            {/if}
          </div>
          <div class="flex flex-col items-end gap-1 shrink-0">
            {#if dataset.source_type}
              <span class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded
                bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                {dataset.source_type}
              </span>
            {/if}
            {#if dataset.loaded}
              <span class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded
                bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400">
                loaded
              </span>
            {:else}
              <span class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded
                bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
                not loaded
              </span>
            {/if}
          </div>
        </div>
        {#if dataset.shape}
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-1">
            {dataset.shape[0].toLocaleString()} rows × {dataset.shape[1]} columns
          </p>
        {/if}
      </div>

      <!-- Not-loaded banner -->
      {#if notLoaded}
        <div class="px-4 pt-3 pb-2 shrink-0">
          <div class="flex items-start gap-3 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
            <Icon icon="mdi:database-off-outline" class="h-5 w-5 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
            <div class="text-xs space-y-1">
              <p class="font-medium text-amber-700 dark:text-amber-300">Dataset not loaded into memory</p>
              <div class="text-amber-600/80 dark:text-amber-400/70 space-y-0.5">
                {#if sourceType}
                  <p>Source: <span class="font-mono">{sourceType}</span></p>
                {/if}
                {#if sourceDescription}
                  <p>{sourceDescription}</p>
                {/if}
              </div>
            </div>
          </div>
        </div>
      {/if}

      <!-- EDA summary cards -->
      {#if edaSummary?.basic_info}
        {@const info = edaSummary.basic_info}
        <div class="px-4 pt-3 pb-2 shrink-0">
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div class="bg-slate-50 dark:bg-slate-800 rounded-lg p-3 text-center">
              <p class="text-lg font-semibold text-slate-700 dark:text-slate-200">{formatNumber(info.total_rows)}</p>
              <p class="text-[10px] uppercase tracking-wide text-slate-400">Rows</p>
            </div>
            <div class="bg-slate-50 dark:bg-slate-800 rounded-lg p-3 text-center">
              <p class="text-lg font-semibold text-slate-700 dark:text-slate-200">{info.total_columns}</p>
              <p class="text-[10px] uppercase tracking-wide text-slate-400">Columns</p>
            </div>
            <div class="bg-slate-50 dark:bg-slate-800 rounded-lg p-3 text-center">
              <p class="text-lg font-semibold text-slate-700 dark:text-slate-200">{formatBytes(info.memory_usage_mb)}</p>
              <p class="text-[10px] uppercase tracking-wide text-slate-400">Memory</p>
            </div>
            <div class="bg-slate-50 dark:bg-slate-800 rounded-lg p-3 text-center">
              <p class="text-lg font-semibold text-slate-700 dark:text-slate-200">
                {edaSummary.data_quality?.completeness_percentage ?? 100}%
              </p>
              <p class="text-[10px] uppercase tracking-wide text-slate-400">Completeness</p>
            </div>
          </div>
        </div>
      {/if}

      <!-- Column schema table -->
      {#if hasColumnMeta}
        <div class="px-4 pt-2 pb-1 shrink-0">
          <h4 class="text-xs font-medium text-slate-600 dark:text-slate-300">
            Column Schema
            <span class="text-slate-400 font-normal">({columnRows.length} columns)</span>
          </h4>
        </div>
        <div class="px-4 pb-3 overflow-y-auto max-h-64">
          <table class="w-full text-xs border-collapse">
            <thead class="sticky top-0 bg-white dark:bg-slate-900 z-10">
              <tr class="border-b border-slate-200 dark:border-slate-700">
                <th class="text-left py-2 pr-3 font-medium text-slate-500 dark:text-slate-400">#</th>
                <th class="text-left py-2 pr-3 font-medium text-slate-500 dark:text-slate-400">Column</th>
                <th class="text-left py-2 pr-3 font-medium text-slate-500 dark:text-slate-400">Description</th>
                <th class="text-left py-2 pr-3 font-medium text-slate-500 dark:text-slate-400">Dtype</th>
                <th class="text-left py-2 font-medium text-slate-500 dark:text-slate-400">Type</th>
              </tr>
            </thead>
            <tbody>
              {#each columnRows as row, i}
                <tr class="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td class="py-1.5 pr-3 text-slate-400 tabular-nums">{i + 1}</td>
                  <td class="py-1.5 pr-3 font-mono text-slate-700 dark:text-slate-200">{row.column}</td>
                  <td class="py-1.5 pr-3 text-slate-500 dark:text-slate-400">{row.description}</td>
                  <td class="py-1.5 pr-3">
                    <span class="inline-block px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-mono text-[10px]">
                      {row.dtype}
                    </span>
                  </td>
                  <td class="py-1.5">
                    <span class="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium
                      {row.type.includes('float') || row.type === 'integer'
                        ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
                        : row.type === 'datetime'
                          ? 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400'
                          : row.type.includes('categorical')
                            ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400'
                            : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'}">
                      {row.type}
                    </span>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

      <!-- Fetch Sample button / Sample data table -->
      {#if !notLoaded}
        <div class="px-4 pb-4 shrink-0">
          {#if !sampleFetched}
            <button
              type="button"
              class="btn btn-sm btn-outline w-full"
              onclick={fetchSample}
              disabled={sampleLoading}
            >
              {#if sampleLoading}
                <span class="loading loading-spinner loading-xs mr-1"></span>
                Loading sample...
              {:else}
                <Icon icon="mdi:table-eye" class="h-4 w-4 mr-1" />
                Fetch Sample (10 rows)
              {/if}
            </button>
          {:else if hasRowData}
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-medium text-slate-600 dark:text-slate-300">Sample Data</span>
              <span class="text-xs text-slate-400">
                Showing {previewData.length} of {totalRows.toLocaleString()} rows
              </span>
            </div>
            <DataTable data={previewData} columns={previewColumns} title="" />
          {:else}
            <p class="text-xs text-slate-400 dark:text-slate-500 text-center italic py-2">
              No row data available for this dataset.
            </p>
          {/if}
        </div>
      {/if}

    </div>
  {/if}
</div>
