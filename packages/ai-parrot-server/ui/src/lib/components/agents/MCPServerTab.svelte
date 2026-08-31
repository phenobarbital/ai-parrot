<script lang="ts">
  import { onMount } from "svelte";

  import Icon from "@iconify/svelte";
  import {
    getAgentMCPServers,
    saveAgentMCPServers,
    type MCPServerEntry,
  } from "$lib/api/agent";
  import { toastStore } from "$lib/stores/toast.svelte";

  let { agentId } = $props<{ agentId: string }>();

  // State
  let servers = $state<MCPServerEntry[]>([]);
  let isLoading = $state(true);
  let isSaving = $state(false);
  let showAddForm = $state(false);
  let hasChanges = $state(false);

  // New server form state
  let newServer = $state<MCPServerEntry>(emptyServer());

  // Auth config sub-fields
  let authApiKey = $state("");
  let authToken = $state("");
  let authUsername = $state("");
  let authPassword = $state("");

  // Headers as editable pairs
  let headerPairs = $state<{ key: string; value: string }[]>([]);

  // Allowed/blocked as comma strings
  let allowedToolsStr = $state("");
  let blockedToolsStr = $state("");

  const transportOptions = [
    { value: "auto", name: "Auto" },
    { value: "http", name: "HTTP" },
    { value: "sse", name: "SSE" },
    { value: "stdio", name: "Stdio" },
  ];

  const authTypeOptions = [
    { value: "none", name: "None" },
    { value: "api_key", name: "API Key" },
    { value: "bearer", name: "Bearer Token" },
    { value: "basic", name: "Basic Auth" },
  ];

  function emptyServer(): MCPServerEntry {
    return {
      name: "",
      url: "",
      transport: "auto",
      auth_type: "none",
      auth_config: {},
      headers: {},
      allowed_tools: null,
      blocked_tools: null,
      description: "",
    };
  }

  function resetAddForm() {
    newServer = emptyServer();
    authApiKey = "";
    authToken = "";
    authUsername = "";
    authPassword = "";
    headerPairs = [];
    allowedToolsStr = "";
    blockedToolsStr = "";
    showAddForm = false;
  }

  onMount(async () => {
    await loadServers();
  });

  async function loadServers() {
    isLoading = true;
    try {
      const result = await getAgentMCPServers(agentId);
      servers = result.mcp_servers || [];
    } catch (error: any) {
      console.error("Failed to load MCP servers:", error);
      // Not an error — just means no session yet
      servers = [];
    } finally {
      isLoading = false;
    }
  }

  function addServer() {
    // Validate
    if (!newServer.name.trim()) {
      toastStore.error("Server name is required.");
      return;
    }
    if (
      newServer.transport !== "stdio" &&
      (!newServer.url || !newServer.url.trim())
    ) {
      toastStore.error("Server URL is required for HTTP/SSE transports.");
      return;
    }

    // Check duplicate
    if (servers.some((s) => s.name === newServer.name.trim())) {
      toastStore.error(`Server "${newServer.name}" already exists.`);
      return;
    }

    // Build auth_config from sub-fields
    const authConfig: Record<string, string> = {};
    if (newServer.auth_type === "api_key" && authApiKey) {
      authConfig.api_key = authApiKey;
    } else if (newServer.auth_type === "bearer" && authToken) {
      authConfig.token = authToken;
    } else if (newServer.auth_type === "basic") {
      if (authUsername) authConfig.username = authUsername;
      if (authPassword) authConfig.password = authPassword;
    }

    // Build headers from pairs
    const headers: Record<string, string> = {};
    for (const pair of headerPairs) {
      if (pair.key.trim()) {
        headers[pair.key.trim()] = pair.value;
      }
    }

    // Build allowed/blocked tools
    const allowed = allowedToolsStr.trim()
      ? allowedToolsStr
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : null;
    const blocked = blockedToolsStr.trim()
      ? blockedToolsStr
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : null;

    const entry: MCPServerEntry = {
      name: newServer.name.trim(),
      url: newServer.url?.trim() || undefined,
      transport: newServer.transport || "auto",
      auth_type: newServer.auth_type || "none",
      auth_config: Object.keys(authConfig).length > 0 ? authConfig : undefined,
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      allowed_tools: allowed,
      blocked_tools: blocked,
      description: newServer.description?.trim() || undefined,
    };

    servers = [...servers, entry];
    hasChanges = true;
    resetAddForm();
    toastStore.info(`Added "${entry.name}" — click Save to persist.`);
  }

  function removeServer(index: number) {
    const name = servers[index]?.name;
    servers = servers.filter((_, i) => i !== index);
    hasChanges = true;
    toastStore.info(`Removed "${name}" — click Save to persist.`);
  }

  function addHeaderPair() {
    headerPairs = [...headerPairs, { key: "", value: "" }];
  }

  function removeHeaderPair(index: number) {
    headerPairs = headerPairs.filter((_, i) => i !== index);
  }

  async function handleSave() {
    isSaving = true;
    try {
      await saveAgentMCPServers(agentId, servers);
      toastStore.success("MCP servers saved to session.");
      hasChanges = false;
      // Reload to get runtime info (connected, tool_count)
      await loadServers();
    } catch (error: any) {
      console.error("Failed to save MCP servers:", error);
      toastStore.error(`Failed to save: ${error.message || "Unknown error"}`);
    } finally {
      isSaving = false;
    }
  }
</script>

<div class="flex flex-col gap-3 pt-1">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div class="flex items-center gap-2">
      <div
        class="flex h-8 w-8 items-center justify-center rounded-md bg-indigo-100 text-indigo-600 dark:bg-indigo-900 dark:text-indigo-400"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="size-4"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7m0 0a3 3 0 0 1-3 3m0 3h.008v.008h-.008v-.008Zm0-6h.008v.008h-.008v-.008Zm-3 6h.008v.008h-.008v-.008Zm0-6h.008v.008h-.008v-.008Z"
          />
        </svg>
      </div>
      <div class="flex flex-col">
        <span class="text-sm font-semibold text-slate-700 dark:text-slate-200">
          MCP Servers
        </span>
        <span class="text-xs text-slate-500 dark:text-slate-400">
          External tool servers connected to this agent
        </span>
      </div>
    </div>
    <div class="flex items-center gap-2">
      {#if hasChanges}
        <button
          class="btn btn-primary btn-sm gap-1 transition-all hover:shadow-md"
          onclick={handleSave}
          disabled={isSaving}
        >
          {#if isSaving}
            <span class="loading loading-spinner w-3 h-3"></span>
          {:else}
            <Icon icon="mdi:check" class="h-3 w-3" />
          {/if}
          Save
        </button>
      {/if}
      <button
        class="btn btn-ghost btn-sm gap-1"
        onclick={() => (showAddForm = !showAddForm)}
      >
        <Icon icon="mdi:plus" class="h-3 w-3" />
        Add
      </button>
    </div>
  </div>

  <!-- Loading -->
  {#if isLoading}
    <div class="flex items-center justify-center py-6 opacity-50">
      <span class="loading loading-spinner w-5 h-5"></span>
      <span class="ml-2 text-sm">Loading MCP servers...</span>
    </div>

    <!-- Server List -->
  {:else if servers.length > 0}
    <div class="flex flex-col gap-2">
      {#each servers as server, index (server.name)}
        <div
          class="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2.5 shadow-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <div class="flex items-center gap-3 min-w-0 flex-1">
            <div class="flex flex-col min-w-0">
              <div class="flex items-center gap-2">
                <span
                  class="text-sm font-medium text-slate-800 dark:text-slate-100 truncate"
                >
                  {server.name}
                </span>
                {#if server.connected}
                  <span
                    class="badge badge-sm text-[10px] bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-400"
                    >Connected</span
                  >
                {:else}
                  <span class="badge badge-sm badge-ghost text-[10px]"
                    >Pending</span
                  >
                {/if}
              </div>
              <div
                class="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400"
              >
                {#if server.url}
                  <span class="truncate max-w-[250px]">{server.url}</span>
                  <span>·</span>
                {/if}
                <span>{server.transport || "auto"}</span>
                {#if server.tool_count}
                  <span>·</span>
                  <span>{server.tool_count} tools</span>
                {/if}
              </div>
            </div>
          </div>
          <button
            class="ml-2 p-1.5 text-slate-400 hover:text-red-500 dark:hover:text-red-400 rounded transition-colors shrink-0"
            onclick={() => removeServer(index)}
            title="Remove server"
          >
            <Icon icon="mdi:delete-outline" class="h-4 w-4" />
          </button>
        </div>
      {/each}
    </div>

    <!-- Empty State -->
  {:else if !showAddForm}
    <div
      class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-200 dark:border-slate-700 py-8 opacity-60"
    >
      <p class="text-sm text-slate-500 dark:text-slate-400 mb-2">
        No MCP servers configured.
      </p>
      <button
        class="btn btn-ghost btn-sm gap-1"
        onclick={() => (showAddForm = true)}
      >
        <Icon icon="mdi:plus" class="h-3 w-3" />
        Add your first server
      </button>
    </div>
  {/if}

  <!-- Add Server Form -->
  {#if showAddForm}
    <div
      class="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-800 dark:bg-indigo-950/30"
    >
      <h4 class="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">
        Add MCP Server
      </h4>
      <div class="grid grid-cols-2 gap-3">
        <!-- Name -->
        <div>
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-name">Name *</label
          >
          <input
            id="mcp-name"
            class="input input-sm w-full"
            bind:value={newServer.name}
            placeholder="weather-api"
          />
        </div>
        <!-- URL -->
        <div>
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-url">URL</label
          >
          <input
            id="mcp-url"
            class="input input-sm w-full"
            bind:value={newServer.url}
            placeholder="https://api.example.com/mcp"
          />
        </div>
        <!-- Transport -->
        <div>
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-transport">Transport</label
          >
          <select
            id="mcp-transport"
            class="select select-sm w-full"
            bind:value={newServer.transport}
          >
            {#each transportOptions as opt}
              <option value={opt.value}>{opt.name}</option>
            {/each}
          </select>
        </div>
        <!-- Auth Type -->
        <div>
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-auth">Auth Type</label
          >
          <select
            id="mcp-auth"
            class="select select-sm w-full"
            bind:value={newServer.auth_type}
          >
            {#each authTypeOptions as opt}
              <option value={opt.value}>{opt.name}</option>
            {/each}
          </select>
        </div>
      </div>

      <!-- Conditional Auth Fields -->
      {#if newServer.auth_type === "api_key"}
        <div class="mt-3">
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-api-key">API Key</label
          >
          <input
            id="mcp-api-key"
            type="password"
            class="input input-sm w-full"
            bind:value={authApiKey}
            placeholder="Your API key"
          />
        </div>
      {:else if newServer.auth_type === "bearer"}
        <div class="mt-3">
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-token">Bearer Token</label
          >
          <input
            id="mcp-token"
            type="password"
            class="input input-sm w-full"
            bind:value={authToken}
            placeholder="Bearer token"
          />
        </div>
      {:else if newServer.auth_type === "basic"}
        <div class="mt-3 grid grid-cols-2 gap-3">
          <div>
            <label
              class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
              for="mcp-user">Username</label
            >
            <input
              id="mcp-user"
              class="input input-sm w-full"
              bind:value={authUsername}
              placeholder="Username"
            />
          </div>
          <div>
            <label
              class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
              for="mcp-pass">Password</label
            >
            <input
              id="mcp-pass"
              type="password"
              class="input input-sm w-full"
              bind:value={authPassword}
              placeholder="Password"
            />
          </div>
        </div>
      {/if}

      <!-- Description -->
      <div class="mt-3">
        <label
          class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
          for="mcp-desc">Description</label
        >
        <input
          id="mcp-desc"
          class="input input-sm w-full"
          bind:value={newServer.description}
          placeholder="Optional description"
        />
      </div>

      <!-- Headers -->
      <div class="mt-3">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs font-medium text-slate-600 dark:text-slate-300"
            >Custom Headers</span
          >
          <button
            class="text-xs text-indigo-600 hover:text-indigo-800 dark:text-indigo-400"
            onclick={addHeaderPair}
          >
            + Add Header
          </button>
        </div>
        {#each headerPairs as pair, i}
          <div class="flex items-center gap-2 mb-1.5">
            <input
              class="input input-sm flex-1"
              bind:value={pair.key}
              placeholder="Header name"
            />
            <input
              class="input input-sm flex-1"
              bind:value={pair.value}
              placeholder="Value"
            />
            <button
              class="p-1 text-slate-400 hover:text-red-500 shrink-0"
              onclick={() => removeHeaderPair(i)}
            >
              <Icon icon="mdi:delete-outline" class="h-3.5 w-3.5" />
            </button>
          </div>
        {/each}
      </div>

      <!-- Tool Filtering -->
      <div class="mt-3 grid grid-cols-2 gap-3">
        <div>
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-allowed">Allowed Tools</label
          >
          <input
            id="mcp-allowed"
            class="input input-sm w-full"
            bind:value={allowedToolsStr}
            placeholder="tool1, tool2 (optional)"
          />
        </div>
        <div>
          <label
            class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1"
            for="mcp-blocked">Blocked Tools</label
          >
          <input
            id="mcp-blocked"
            class="input input-sm w-full"
            bind:value={blockedToolsStr}
            placeholder="tool3, tool4 (optional)"
          />
        </div>
      </div>

      <!-- Form Actions -->
      <div
        class="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-indigo-200 dark:border-indigo-800"
      >
        <button class="btn btn-ghost btn-sm" onclick={resetAddForm}
          >Cancel</button
        >
        <button class="btn btn-primary btn-sm" onclick={addServer}>
          <Icon icon="mdi:plus" class="h-3 w-3 mr-1" />
          Add Server
        </button>
      </div>
    </div>
  {/if}
</div>
