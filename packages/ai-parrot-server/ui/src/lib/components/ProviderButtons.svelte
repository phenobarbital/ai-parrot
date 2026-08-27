<!--
  ProviderButtons (TASK-2528) — renders SSO/external auth providers
  discovered from GET /api/v1/auth/methods.

  Adapted (not copied) from navauth's ProviderButtons.svelte: the source
  drives a full corporate OAuth popup flow (`NavAuthStore.login()` +
  `src/lib/oauth/popup.ts`) that this foundation task does not vendor —
  per the Codebase Contract's explicit fallback, "else render provider
  buttons as plain links/disabled with a tooltip". `external` providers
  link straight to their server-side redirect URI; non-external providers
  (no client-side flow implemented yet) render disabled with a tooltip.

  BasicAuth is always excluded — the login form on this page already
  covers it.
-->
<script lang="ts">
  import { config } from "$lib/config";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";

  export interface AuthMethodInfo {
    name: string;
    uri: string;
    description: string;
    icon: string;
    external: boolean;
    headers: Record<string, string>;
  }

  interface Props {
    /** Raw GET /api/v1/auth/methods response: {<backend_key>: AuthMethodInfo}. */
    methods: Record<string, AuthMethodInfo> | null;
  }

  let { methods }: Props = $props();

  function isBasicAuth(info: AuthMethodInfo): boolean {
    const header = info.headers?.["x-auth-method"];
    return typeof header === "string" && header.toLowerCase() === "basicauth";
  }

  const providers = $derived(
    methods
      ? Object.entries(methods)
          .map(([key, info]) => ({ key, info }))
          .filter(({ info }) => !isBasicAuth(info))
      : [],
  );
</script>

{#if providers.length > 0}
  <div class="flex items-center gap-3 text-xs text-muted-foreground" role="separator">
    <div class="h-px flex-1 bg-border"></div>
    <span>Or continue with</span>
    <div class="h-px flex-1 bg-border"></div>
  </div>

  <div class="flex flex-col gap-2" data-testid="provider-buttons">
    {#each providers as { key, info } (key)}
      {#if info.external}
        <Button variant="outline" href={`${config.apiBaseUrl}${info.uri}`} class="w-full">
          {info.description || info.name}
        </Button>
      {:else}
        <Button
          variant="outline"
          disabled
          title="Not yet supported in this Admin UI"
          class="w-full"
        >
          {info.description || info.name}
        </Button>
      {/if}
    {/each}
  </div>
{/if}
