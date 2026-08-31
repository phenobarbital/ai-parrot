<script lang="ts">
  import { toastStore } from "$lib/stores/toast.svelte";
  import {
    listIntegrations,
    startIntegrationConnect,
    confirmIntegrationEnable,
    disconnectIntegration,
    type IntegrationDescriptor,
  } from "$lib/api/integrations";
  import { awaitOAuthCallback } from "$lib/oauth/popup";
  import Icon from "@iconify/svelte";
  import IntegrationItem from "./IntegrationItem.svelte";

  let { agentId }: { agentId: string } = $props();

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let open = $state(false);
  let integrations = $state<IntegrationDescriptor[]>([]);
  let loadingProvider = $state<string | null>(null);
  let fetching = $state(false);
  let fetchError = $state<string | null>(null);

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------
  async function loadIntegrations(): Promise<void> {
    fetching = true;
    fetchError = null;
    try {
      integrations = await listIntegrations(agentId);
    } catch (err: unknown) {
      fetchError = err instanceof Error ? err.message : "Failed to load integrations";
    } finally {
      fetching = false;
    }
  }

  function toggleMenu(): void {
    open = !open;
    if (open) {
      loadIntegrations();
    }
  }

  // ---------------------------------------------------------------------------
  // Connect flow
  // ---------------------------------------------------------------------------
  async function handleConnect(provider: string): Promise<void> {
    loadingProvider = provider;
    try {
      const { auth_url } = await startIntegrationConnect(
        agentId,
        provider,
        window.location.origin,
      );
      const result = await awaitOAuthCallback({
        authUrl: auth_url,
        allowedOrigin: window.location.origin,
      });

      if (result.success) {
        await confirmIntegrationEnable(agentId, provider);
        toastStore.success(`Connected to ${provider}`);
        await loadIntegrations();
      } else if (result.reason === "popup-blocked") {
        toastStore.error("Popup blocked. Please allow popups for this site and try again.");
      } else if (result.reason === "cancelled") {
        // User closed the popup voluntarily — no toast needed.
      } else if (result.reason === "timeout") {
        toastStore.error("Authorization timed out. Please try again.");
      } else if (result.reason === "error") {
        toastStore.error(`Authorization failed: ${result.error ?? "unknown error"}`);
      }
    } catch (err: unknown) {
      toastStore.error(
        `Failed to connect: ${err instanceof Error ? err.message : "unknown error"}`,
      );
    } finally {
      loadingProvider = null;
    }
  }

  // ---------------------------------------------------------------------------
  // Disconnect flow
  // ---------------------------------------------------------------------------
  async function handleDisconnect(provider: string): Promise<void> {
    loadingProvider = provider;
    try {
      await disconnectIntegration(agentId, provider);
      toastStore.success(`Disconnected from ${provider}`);
      await loadIntegrations();
    } catch (err: unknown) {
      toastStore.error(
        `Failed to disconnect: ${err instanceof Error ? err.message : "unknown error"}`,
      );
    } finally {
      loadingProvider = null;
    }
  }
</script>

<!-- Wrapper uses DaisyUI dropdown pattern (matches existing toolbar dropdowns) -->
<div class="dropdown dropdown-end">
  <!-- Trigger button — same style as other toolbar buttons -->
  <button
    class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
    onclick={toggleMenu}
    title="Integrations"
    aria-label="Open integrations menu"
    aria-expanded={open}
  >
    <Icon icon="mdi:puzzle-plus-outline" class="size-3.5" />
  </button>

  {#if open}
    <!-- Backdrop to close on outside click -->
    <button
      class="fixed inset-0 z-[49] cursor-default bg-transparent border-none p-0"
      onclick={() => (open = false)}
      aria-label="Close integrations menu"
      tabindex="-1"
    ></button>

    <!-- Dropdown panel -->
    <div
      class="dropdown-content absolute right-0 top-full mt-1 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 z-[50] w-72 p-0 shadow-lg"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-3 py-2 border-b border-slate-100 dark:border-slate-700">
        <span class="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">
          Integrations
        </span>
        <button
          class="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          onclick={() => (open = false)}
          aria-label="Close integrations menu"
        >
          ✕
        </button>
      </div>

      <!-- Body -->
      <div class="max-h-60 overflow-y-auto">
        {#if fetching}
          <div class="flex items-center justify-center py-4">
            <span class="loading loading-spinner loading-xs text-slate-400"></span>
          </div>
        {:else if fetchError}
          <p class="text-xs text-error px-3 py-3">{fetchError}</p>
        {:else if integrations.length === 0}
          <p class="text-xs text-slate-400 px-3 py-3">No integrations available</p>
        {:else}
          {#each integrations as integration (integration.provider)}
            <IntegrationItem
              {integration}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
              loading={loadingProvider === integration.provider}
            />
          {/each}
        {/if}
      </div>
    </div>
  {/if}
</div>
