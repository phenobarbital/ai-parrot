<script lang="ts">
  import type { IntegrationDescriptor } from "$lib/api/integrations";
  import Icon from "@iconify/svelte";

  let {
    integration,
    onConnect,
    onDisconnect,
    loading = false,
  }: {
    integration: IntegrationDescriptor;
    onConnect: (provider: string) => void;
    onDisconnect: (provider: string) => void;
    loading?: boolean;
  } = $props();
</script>

<div class="flex items-center justify-between px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
  <!-- Left: icon + name + status -->
  <div class="flex items-center gap-2 min-w-0">
    {#if integration.icon}
      <Icon icon={integration.icon} class="size-4 flex-shrink-0 text-slate-500" />
    {:else}
      <Icon icon="mdi:puzzle-outline" class="size-4 flex-shrink-0 text-slate-500" />
    {/if}
    <div class="min-w-0">
      <p class="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
        {integration.display_name}
      </p>
      {#if integration.connected && integration.display_account_name}
        <p class="text-[10px] text-slate-400 truncate">{integration.display_account_name}</p>
      {/if}
    </div>
  </div>

  <!-- Right: status badge + action button -->
  <div class="flex items-center gap-2 flex-shrink-0 ml-2">
    {#if integration.connected}
      <span class="badge badge-xs badge-success">Connected</span>
      <button
        class="btn btn-ghost btn-xs text-error hover:bg-error/10"
        onclick={() => onDisconnect(integration.provider)}
        disabled={loading}
        title="Disconnect {integration.display_name}"
      >
        Disconnect
      </button>
    {:else}
      <span class="badge badge-xs badge-ghost text-slate-400">Not connected</span>
      <button
        class="btn btn-ghost btn-xs text-primary hover:bg-primary/10"
        onclick={() => onConnect(integration.provider)}
        disabled={loading}
        title="Connect {integration.display_name}"
      >
        Connect
      </button>
    {/if}
  </div>
</div>
