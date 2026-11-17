<script lang="ts">
  import { awaitOAuthCallback } from "$lib/oauth/popup";
  import { toastStore } from "$lib/stores/toast.svelte";
  import { connectionsStore } from "$lib/stores/connections.svelte";
  import { disconnect, startConnect } from "$lib/api/connections";
  import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";

  let busy = $state<string | null>(null);

  function accountName(connection: IntegrationDescriptor): string {
    return connection.display_account_name ?? connection.email ?? "Not connected";
  }

  function expiry(expiresAt: number | null | undefined): string {
    return expiresAt ? new Date(expiresAt * 1000).toLocaleString() : "Never";
  }

  function status(connection: IntegrationDescriptor): string {
    return connection.status ?? (connection.connected ? "connected" : "disconnected");
  }

  async function connect(connection: IntegrationDescriptor): Promise<void> {
    busy = connection.provider;
    try {
      const { auth_url } = await startConnect(connection.provider, window.location.origin);
      const result = await awaitOAuthCallback({
        authUrl: auth_url,
        allowedOrigin: window.location.origin,
      });

      if (result.success) {
        toastStore.success(`Connected to ${connection.display_name}`);
        await connectionsStore.refresh();
      } else if (result.reason === "popup-blocked") {
        toastStore.error("Popup blocked. Please allow popups for this site and try again.");
      } else if (result.reason === "cancelled") {
        // User closed the popup voluntarily; no toast is needed.
      } else if (result.reason === "timeout") {
        toastStore.error("Authorization timed out. Please try again.");
      } else {
        toastStore.error(`Authorization failed: ${result.error ?? "unknown error"}`);
      }
    } catch (err: unknown) {
      toastStore.error(`Failed to connect: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      busy = null;
    }
  }

  async function remove(connection: IntegrationDescriptor): Promise<void> {
    busy = connection.provider;
    try {
      await disconnect(connection.provider);
      toastStore.success(`Disconnected from ${connection.display_name}`);
      await connectionsStore.refresh();
    } catch (err: unknown) {
      toastStore.error(`Failed to disconnect: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      busy = null;
    }
  }
</script>

<div class="flex flex-col gap-4">
  {#if connectionsStore.loading && connectionsStore.items.length === 0}
    <p class="text-muted-foreground text-sm" data-testid="connections-loading">Loading connections…</p>
  {:else if connectionsStore.items.length === 0}
    <p class="text-muted-foreground text-sm" data-testid="connections-empty">No connections are registered.</p>
  {:else}
    <div class="overflow-x-auto">
      <table class="w-full text-left text-sm" data-testid="connections-table">
        <thead>
          <tr class="border-b text-muted-foreground">
            <th class="px-2 py-2 font-medium">Provider</th>
            <th class="px-2 py-2 font-medium">Status</th>
            <th class="px-2 py-2 font-medium">Account</th>
            <th class="px-2 py-2 font-medium">Scopes</th>
            <th class="px-2 py-2 font-medium">Expires</th>
            <th class="px-2 py-2 font-medium">Channels</th>
            <th class="px-2 py-2 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each connectionsStore.items as connection (connection.provider)}
            {@const connectionStatus = status(connection)}
            <tr data-testid={`connection-${connection.provider}`}>
              <td class="px-2 py-3">{connection.display_name}</td>
              <td class="px-2 py-3">
                <span class="rounded-full border px-2 py-1 text-xs" data-testid={`status-${connection.provider}`}>
                  {connectionStatus}
                </span>
              </td>
              <td class="px-2 py-3">{accountName(connection)}</td>
              <td class="px-2 py-3">{connection.scopes_granted?.join(", ") || "—"}</td>
              <td class="px-2 py-3">{expiry(connection.expires_at)}</td>
              <td class="px-2 py-3">{connection.channels?.join(", ") || "—"}</td>
              <td class="px-2 py-3">
                <div class="flex gap-2">
                  {#if connectionStatus === "connected"}
                    <Button
                      variant="outline"
                      size="sm"
                      onclick={() => remove(connection)}
                      disabled={busy === connection.provider}
                    >
                      Disconnect
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onclick={() => connect(connection)}
                      disabled={busy === connection.provider}
                    >
                      Reconnect
                    </Button>
                  {:else}
                    <Button
                      size="sm"
                      onclick={() => connect(connection)}
                      disabled={busy === connection.provider}
                    >
                      {connectionStatus === "needs_reconnect" ? "Reconnect" : "Connect"}
                    </Button>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
