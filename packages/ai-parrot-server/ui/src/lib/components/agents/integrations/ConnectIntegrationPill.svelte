<script lang="ts">
  import { confirmIntegrationEnable } from "$lib/api/integrations";
  import { awaitOAuthCallback } from "$lib/oauth/popup";
  import { toastStore } from "$lib/stores/toast.svelte";
  import Icon from "@iconify/svelte";

  let {
    provider,
    authUrl,
    message,
    agentId,
  }: {
    provider: string;
    authUrl: string;
    message: string;
    agentId: string;
  } = $props();

  let connecting = $state(false);

  async function handleConnect(): Promise<void> {
    connecting = true;
    try {
      const result = await awaitOAuthCallback({
        authUrl,
        allowedOrigin: window.location.origin,
      });

      if (result.success) {
        await confirmIntegrationEnable(agentId, provider);
        toastStore.success(
          `Connected to ${provider}! You can now retry your prompt.`,
        );
      } else if (result.reason === "popup-blocked") {
        toastStore.error(
          "Popup blocked. Please allow popups for this site and try again.",
        );
      } else if (result.reason === "cancelled") {
        // User closed voluntarily — no toast needed.
      } else if (result.reason === "timeout") {
        toastStore.error("Authorization timed out. Please try again.");
      } else if (result.reason === "error") {
        toastStore.error(`Authorization failed: ${result.error ?? "unknown error"}`);
      }
    } catch (err: unknown) {
      toastStore.error(
        `Connection failed: ${err instanceof Error ? err.message : "unknown error"}`,
      );
    } finally {
      connecting = false;
    }
  }
</script>

<!--
  Renders as an assistant message bubble containing the auth_required message
  and a "Connect [Provider]" action button.
-->
<div class="flex justify-start px-2 py-1">
  <div
    class="max-w-[80%] rounded-xl rounded-tl-sm bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 px-4 py-3 shadow-sm"
  >
    <!-- Warning icon + message -->
    <div class="flex items-start gap-2 mb-3">
      <Icon
        icon="mdi:lock-outline"
        class="size-4 flex-shrink-0 mt-0.5 text-amber-600 dark:text-amber-400"
      />
      <p class="text-sm text-slate-700 dark:text-slate-300 leading-snug">
        {message}
      </p>
    </div>

    <!-- Connect button -->
    <button
      class="btn btn-sm btn-primary"
      onclick={handleConnect}
      disabled={connecting}
    >
      {#if connecting}
        <span class="loading loading-spinner loading-xs"></span>
        Connecting…
      {:else}
        <Icon icon="mdi:link-variant-plus" class="size-4" />
        Connect {provider}
      {/if}
    </button>
  </div>
</div>
