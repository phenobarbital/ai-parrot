<script lang="ts">
  import { uploadDataset, addQueryDataset } from '$lib/api/agent';
  import type { DatasetAddResponse } from '$lib/types/dataset';
  import Icon from '@iconify/svelte';

  let {
    agentId,
    onCreated,
  }: {
    agentId: string;
    onCreated: (result: DatasetAddResponse) => void;
  } = $props();

  type Mode = 'slug' | 'sql' | 'file' | 'table' | 'smartsheet';

  let mode = $state<Mode>('slug');
  // slug / sql / file
  let querySlug = $state('');
  let query = $state('');
  let file = $state<File | null>(null);
  // sql
  let sqlDriver = $state('');
  // table
  let tableName = $state('');
  let tableTarget = $state('');
  let tableDriver = $state('');
  let tableDsn = $state('');
  // smartsheet
  let sheetName = $state('');
  let sheetId = $state('');
  let accessToken = $state('');

  let submitting = $state(false);
  let error = $state('');

  function reset() {
    querySlug = '';
    query = '';
    file = null;
    sqlDriver = '';
    tableName = '';
    tableTarget = '';
    tableDriver = '';
    tableDsn = '';
    sheetName = '';
    sheetId = '';
    accessToken = '';
    error = '';
  }

  async function handleSubmit() {
    error = '';

    if (mode === 'slug') {
      if (!querySlug.trim()) { error = 'Query slug is required.'; return; }
    } else if (mode === 'sql') {
      if (!query.trim()) { error = 'SQL query is required.'; return; }
    } else if (mode === 'file') {
      if (!file) { error = 'Please select a file to upload.'; return; }
    } else if (mode === 'table') {
      if (!tableName.trim()) { error = 'Dataset name is required.'; return; }
      if (!tableTarget.trim()) { error = 'Table name is required.'; return; }
      if (!tableDriver.trim()) { error = 'Database driver is required.'; return; }
    } else if (mode === 'smartsheet') {
      if (!sheetName.trim()) { error = 'Dataset name is required.'; return; }
      if (!sheetId.trim()) { error = 'Sheet ID is required.'; return; }
    }

    submitting = true;
    try {
      let result: DatasetAddResponse;
      if (mode === 'slug') {
        result = await addQueryDataset(agentId, { query: '', query_slug: querySlug.trim() });
      } else if (mode === 'sql') {
        result = await addQueryDataset(agentId, {
          query: query.trim(),
          query_slug: '',
          ...(sqlDriver ? { driver: sqlDriver } : {}),
        });
      } else if (mode === 'file') {
        const formData = new FormData();
        formData.append('file', file!);
        result = await uploadDataset(agentId, formData);
      } else if (mode === 'table') {
        result = await addQueryDataset(agentId, {
          name: tableName.trim(),
          datasource: {
            type: 'table',
            table: tableTarget.trim(),
            driver: tableDriver.trim(),
            dsn: tableDsn.trim() || undefined,
          },
        });
      } else {
        result = await addQueryDataset(agentId, {
          name: sheetName.trim(),
          datasource: {
            type: 'smartsheet',
            sheet_id: sheetId.trim(),
            access_token: accessToken.trim() || undefined,
          },
        });
      }
      onCreated(result);
      reset();
    } catch (e: any) {
      error = e?.response?.data?.message ?? e?.response?.data?.error ?? e?.message ?? 'Failed to add dataset. Please try again.';
    } finally {
      submitting = false;
    }
  }

  const tabs: { id: Mode; label: string; icon: string }[] = [
    { id: 'slug',       label: 'Query Slug',  icon: 'mdi:tag-text-outline' },
    { id: 'sql',        label: 'SQL Query',   icon: 'mdi:database-search' },
    { id: 'file',       label: 'File Upload', icon: 'mdi:file-upload-outline' },
    { id: 'table',      label: 'Table',       icon: 'mdi:table-large' },
    { id: 'smartsheet', label: 'Smartsheet',  icon: 'mdi:google-spreadsheet' },
  ];
</script>

<div class="flex h-full min-h-[350px]">
  <!-- Left panel: type selector -->
  <div class="w-[200px] shrink-0 border-r border-slate-200 dark:border-slate-700 flex flex-col gap-1 p-2 overflow-y-auto">
    {#each tabs as tab}
      <button
        type="button"
        class="flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-left transition-colors w-full
          {mode === tab.id
            ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 font-medium'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'}"
        onclick={() => { mode = tab.id; error = ''; }}
      >
        <Icon icon={tab.icon} class="h-5 w-5 shrink-0" />
        <span>{tab.label}</span>
      </button>
    {/each}
  </div>

  <!-- Right panel: form fields -->
  <div class="flex-1 overflow-y-auto p-4 flex flex-col gap-4">

    <!-- Query Slug mode -->
    {#if mode === 'slug'}
      <label class="flex flex-col gap-1">
        <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Query Slug</span>
        <input
          class="input w-full"
          type="text"
          placeholder="e.g. sales_by_region"
          bind:value={querySlug}
          disabled={submitting}
        />
        <span class="text-xs text-gray-400 dark:text-gray-500">
          Reference an existing registered query by its slug identifier.
        </span>
      </label>

    <!-- SQL Query mode -->
    {:else if mode === 'sql'}
      <label class="flex flex-col gap-1">
        <span class="text-sm font-medium text-gray-700 dark:text-gray-300">
          Database Driver <span class="text-xs font-normal text-gray-400">(optional)</span>
        </span>
        <select class="select w-full" bind:value={sqlDriver} disabled={submitting}>
          <option value="">Auto-detect</option>
          <option value="pg">PostgreSQL</option>
          <option value="bigquery">BigQuery</option>
          <option value="mysql">MySQL</option>
          <option value="sqlite">SQLite</option>
        </select>
        <span class="text-xs text-gray-400 dark:text-gray-500">
          Database engine for the query. Leave as auto-detect if unsure.
        </span>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-sm font-medium text-gray-700 dark:text-gray-300">SQL Query</span>
        <textarea
          class="textarea w-full font-mono text-sm"
          rows={7}
          placeholder="SELECT * FROM table WHERE ..."
          bind:value={query}
          disabled={submitting}
        ></textarea>
      </label>

    <!-- File Upload mode -->
    {:else if mode === 'file'}
      <label class="flex flex-col gap-1">
        <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Upload CSV or Excel</span>
        <input
          class="input w-full"
          type="file"
          accept=".csv,.xlsx,.xls"
          disabled={submitting}
          onchange={(e) => {
            const input = e.currentTarget as HTMLInputElement;
            file = input.files?.[0] ?? null;
            error = '';
          }}
        />
        <span class="text-xs text-gray-400 dark:text-gray-500">
          Accepted formats: .csv, .xlsx, .xls
        </span>
      </label>

    <!-- Table mode -->
    {:else if mode === 'table'}
      <div class="flex flex-col gap-3">
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Name <span class="text-red-500">*</span></span>
          <input
            class="input w-full"
            type="text"
            placeholder="e.g. orders_dataset"
            bind:value={tableName}
            disabled={submitting}
          />
          <span class="text-xs text-gray-400 dark:text-gray-500">Dataset identifier used in queries.</span>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Table <span class="text-red-500">*</span></span>
          <input
            class="input w-full"
            type="text"
            placeholder="e.g. public.orders"
            bind:value={tableTarget}
            disabled={submitting}
          />
          <span class="text-xs text-gray-400 dark:text-gray-500">Database table name, optionally schema-qualified.</span>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Driver <span class="text-red-500">*</span></span>
          <select class="select w-full" bind:value={tableDriver} disabled={submitting}>
            <option value="">Select driver...</option>
            <option value="pg">PostgreSQL</option>
            <option value="bigquery">BigQuery</option>
            <option value="mysql">MySQL</option>
            <option value="sqlite">SQLite</option>
          </select>
          <span class="text-xs text-gray-400 dark:text-gray-500">Database driver for the table connection.</span>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">DSN <span class="text-xs font-normal text-gray-400">(optional)</span></span>
          <input
            class="input w-full"
            type="text"
            placeholder="postgresql://user:pass@host/db"
            bind:value={tableDsn}
            disabled={submitting}
          />
          <span class="text-xs text-gray-400 dark:text-gray-500">Connection string — leave blank if configured server-side.</span>
        </label>
      </div>

    <!-- Smartsheet mode -->
    {:else if mode === 'smartsheet'}
      <div class="flex flex-col gap-3">
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Name <span class="text-red-500">*</span></span>
          <input
            class="input w-full"
            type="text"
            placeholder="e.g. sales_pipeline"
            bind:value={sheetName}
            disabled={submitting}
          />
          <span class="text-xs text-gray-400 dark:text-gray-500">Dataset identifier used in queries.</span>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Sheet ID <span class="text-red-500">*</span></span>
          <input
            class="input w-full"
            type="text"
            placeholder="e.g. 1234567890"
            bind:value={sheetId}
            disabled={submitting}
          />
          <span class="text-xs text-gray-400 dark:text-gray-500">Smartsheet sheet ID (found in the sheet URL).</span>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Access Token <span class="text-xs font-normal text-gray-400">(optional)</span></span>
          <input
            class="input w-full"
            type="password"
            placeholder="your-smartsheet-token"
            bind:value={accessToken}
            disabled={submitting}
          />
          <span class="text-xs text-gray-400 dark:text-gray-500">Leave blank if token is configured server-side.</span>
        </label>
      </div>
    {/if}

    <!-- Error -->
    {#if error}
      <p class="text-sm text-red-600 dark:text-red-400">{error}</p>
    {/if}

    <!-- Actions -->
    <div class="flex justify-end gap-2 pt-1">
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        onclick={reset}
        disabled={submitting}
      >
        Clear
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        onclick={handleSubmit}
        disabled={submitting}
      >
        {submitting ? 'Adding...' : 'Add Dataset'}
      </button>
    </div>
  </div>
</div>
