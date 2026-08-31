<script lang="ts">
  import { AppDialog, AppTabs } from "$lib/ui/components";
  import Icon from "@iconify/svelte";
  import {
    refreshAgentData,
    uploadAgentData,
    addAgentQuery,
  } from "$lib/api/agent";
  import { toastStore } from "$lib/stores/toast.svelte";
  import { notificationStore } from "$lib/stores/notifications.svelte";
  import MCPServerTab from "./MCPServerTab.svelte";

  // Props
  let {
    open = $bindable(false),
    agentId,
    explainPrompt = $bindable(""),
  } = $props<{
    open: boolean;
    agentId: string;
    explainPrompt?: string;
  }>();

  let displayName = $derived(
    agentId
      .replace(/[_-]+/g, " ")
      .split(" ")
      .filter(Boolean)
      .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ")
  );

  // Local state
  let uploadFiles = $state<FileList | null>(null);
  let querySlug = $state("");
  let isRefreshing = $state(false);
  let uploadStatus = $state<{
    type: "success" | "error" | null;
    message: string;
  }>({ type: null, message: "" });
  let queryStatus = $state<{
    type: "success" | "error" | null;
    message: string;
  }>({ type: null, message: "" });

  async function handleRefreshData() {
    isRefreshing = true;
    try {
      toastStore.info("Refreshing Agent Data... This may take a moment.");
      notificationStore.add({
        title: "Data Refresh Started",
        message: `Refresh started for agent ${agentId}`,
        type: "info",
      });

      const result = await refreshAgentData(agentId);

      if (result === undefined || result === null) {
        const msg =
          "Data Refresh Complete: No active datasets returned content.";
        toastStore.success(msg);
        notificationStore.add({
          title: "Refresh Complete",
          message: msg,
          type: "success",
        });
      } else if (result.refreshed_data) {
        const count = Object.keys(result.refreshed_data).length;
        const msg = `Data Refresh Complete: Reloaded ${count} datasets.`;
        toastStore.success(msg);
        notificationStore.add({
          title: "Refresh Complete",
          message: msg,
          type: "success",
        });
      } else {
        const msg = `Data Refresh Complete: ${result.message || "Operation finished."}`;
        toastStore.success(msg);
        notificationStore.add({
          title: "Refresh Complete",
          message: msg,
          type: "success",
        });
      }
    } catch (error: any) {
      console.error("Refresh Error", error);
      const msg = `Refresh Failed: ${error.message || "Unknown error occurred."}`;
      toastStore.error(msg);
      notificationStore.add({
        title: "Refresh Failed",
        message: msg,
        type: "error",
      });
    } finally {
      isRefreshing = false;
    }
  }

  async function handleUploadExcel() {
    if (!uploadFiles || uploadFiles.length === 0) {
      uploadStatus = {
        type: "error",
        message: "Please select a file first.",
      };
      return;
    }
    const file = uploadFiles[0];
    if (!file.name.endsWith(".xlsx") && !file.name.endsWith(".xls")) {
      uploadStatus = {
        type: "error",
        message: "Only Excel files (.xlsx, .xls) are allowed.",
      };
      return;
    }

    uploadStatus = { type: null, message: "Uploading..." };
    const formData = new FormData();
    formData.append("file", file);

    try {
      await uploadAgentData(agentId, formData);
      uploadStatus = { type: "success", message: "Uploaded" };
      uploadFiles = null;
      setTimeout(() => {
        uploadStatus = { type: null, message: "" };
      }, 3000);
    } catch (error: any) {
      console.error("Upload Error", error);
      uploadStatus = {
        type: "error",
        message: error.message || "Upload failed.",
      };
    }
  }

  async function handleAddQuery() {
    if (!querySlug.trim()) {
      queryStatus = { type: "error", message: "Please enter a slug." };
      return;
    }

    queryStatus = { type: null, message: "Adding..." };
    try {
      await addAgentQuery(agentId, querySlug);
      queryStatus = { type: "success", message: "Query added." };
      querySlug = "";
      setTimeout(() => {
        queryStatus = { type: null, message: "" };
      }, 3000);
    } catch (error: any) {
      console.error("Add Query Error", error);
      queryStatus = {
        type: "error",
        message: error.message || "Failed to add query.",
      };
    }
  }
</script>

<AppDialog
  bind:open
  eyebrow="Settings"
  title={displayName}
  size="lg"
>
  <div class="flex h-[480px] flex-col">
  <AppTabs tabs={[
    { value: 'data', title: 'Data Management' },
    { value: 'explain', title: 'Explain This' },
    { value: 'mcp', title: 'MCP Servers' },
    { value: 'appearance', title: 'Appearance' }
  ]} fillHeight>
    {#snippet children(tab)}
    <div class="h-full overflow-y-auto pr-1">
    {#if tab === 'data'}
      <div class="flex flex-col gap-3 pt-1">
        <!-- Refresh Data -->
        <div
          class="rounded-lg border border-slate-200 bg-white py-3 px-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <div class="flex items-center justify-between gap-4">
            <div class="flex items-center gap-3 shrink-0">
              <div
                class="flex h-8 w-8 items-center justify-center rounded-md bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400"
              >
                <Icon icon="mdi:refresh" class="h-4 w-4" />
              </div>
              <div class="flex flex-col">
                <span
                  class="text-sm font-semibold text-slate-700 dark:text-slate-200"
                  >Refresh Data</span
                >
                <span class="text-xs text-slate-500 dark:text-slate-400"
                  >Reloads all datasets from source</span
                >
              </div>
            </div>
            <div class="flex items-center gap-2 flex-1 justify-end">
              <button
                class="btn btn-primary btn-sm h-9 w-20 transition-all hover:shadow-md"
                onclick={handleRefreshData}
                disabled={isRefreshing}
              >
                {#if isRefreshing}Running...{:else}Refresh{/if}
              </button>
            </div>
          </div>
        </div>

        <!-- Upload Excel -->
        <div
          class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <div class="flex items-center gap-3 mb-3">
            <div
              class="flex h-8 w-8 items-center justify-center rounded-md bg-green-100 text-green-600 dark:bg-green-900 dark:text-green-400"
            >
              <Icon icon="mdi:file-chart" class="h-4 w-4" />
            </div>
            <div class="flex flex-col">
              <span
                class="text-sm font-semibold text-slate-700 dark:text-slate-200"
                >Upload Excel</span
              >
              <span class="text-xs text-slate-500 dark:text-slate-400"
                >Upload .xlsx file as dataset</span
              >
            </div>
          </div>
          <div class="flex items-center gap-2">
            <label
              class="flex-1 flex items-center justify-center h-10 border border-dashed border-slate-300 rounded-md cursor-pointer bg-slate-50 hover:bg-slate-100 dark:bg-slate-700 dark:border-slate-600 dark:hover:bg-slate-600 transition-colors"
            >
              {#if uploadFiles && uploadFiles.length > 0}
                <span
                  class="text-xs text-green-600 font-medium dark:text-green-400 truncate px-2"
                  >{uploadFiles[0].name}</span
                >
              {:else}
                <span class="text-xs text-slate-500 dark:text-slate-400"
                  >Click to choose .xlsx file</span
                >
              {/if}
              <input
                type="file"
                class="hidden"
                accept=".xlsx"
                bind:files={uploadFiles}
              />
            </label>
            <button
              class="btn btn-primary btn-sm h-10 w-20 transition-all hover:shadow-md"
              onclick={handleUploadExcel}
              disabled={!uploadFiles || uploadFiles.length === 0}
            >
              Upload
            </button>
          </div>
          {#if uploadStatus.type}
            <p
              class={`mt-2 text-xs font-medium ${uploadStatus.type === "error" ? "text-red-500" : "text-green-500"}`}
            >
              {uploadStatus.message}
            </p>
          {/if}
        </div>

        <!-- Add Query -->
        <div
          class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <div class="flex items-center gap-3 mb-3">
            <div
              class="flex h-8 w-8 items-center justify-center rounded-md bg-purple-100 text-purple-600 dark:bg-purple-900 dark:text-purple-400"
            >
              <Icon icon="mdi:database" class="h-4 w-4" />
            </div>
            <div class="flex flex-col">
              <span
                class="text-sm font-semibold text-slate-700 dark:text-slate-200"
                >Add Query</span
              >
              <span class="text-xs text-slate-500 dark:text-slate-400"
                >Register new SQL query slug</span
              >
            </div>
          </div>
          <div class="flex items-center gap-2">
            <input
              class="input input-sm flex-1 h-10"
              bind:value={querySlug}
              placeholder="Query slug (e.g. 'sales_by_region')"
            />
            <button
              class="btn btn-primary btn-sm h-10 w-20 transition-all hover:shadow-md"
              onclick={handleAddQuery}
              disabled={!querySlug.trim()}
            >
              Add
            </button>
          </div>
          {#if queryStatus.type}
            <p
              class={`mt-2 text-xs font-medium ${queryStatus.type === "error" ? "text-red-500" : "text-green-500"}`}
            >
              {queryStatus.message}
            </p>
          {/if}
        </div>
      </div>
    {/if}
    {#if tab === 'explain'}
      <div class="flex flex-col gap-3 py-4">
        <div class="space-y-2">
          <label
            for="explain-prompt"
            class="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            Custom Explanation Prompt
          </label>
          <textarea
            id="explain-prompt"
            bind:value={explainPrompt}
            rows="4"
            class="block w-full rounded-lg border border-slate-300 bg-slate-50 p-2.5 text-sm text-slate-900 focus:border-blue-500 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white dark:placeholder-slate-400 dark:focus:border-blue-500 dark:focus:ring-blue-500"
            placeholder="Enter your custom prompt here..."
          ></textarea>
          <p class="text-xs text-slate-500 dark:text-slate-400">
            This prompt will be used when you click "Explain this" on a chart or
            table. If the data is small (≤ 10x10), it will be automatically
            appended to the prompt as a markdown table.
          </p>
        </div>
      </div>
    {/if}
    {#if tab === 'mcp'}
      <MCPServerTab {agentId} />
    {/if}
    {#if tab === 'appearance'}
      <div class="py-4">
        <p class="opacity-70">Theme settings coming soon...</p>
      </div>
    {/if}
    </div>
    {/snippet}
  </AppTabs>
  </div>
</AppDialog>
