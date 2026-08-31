<!--
  AgentFormPage (TASK-2587, FEAT-475) — route wrapper for
  `/admin/agents/new` (create) and `/admin/agents/:name` (edit). Reads
  `router.params.name` to derive `mode`; loads the catalog + tools list
  (needed by every tab, not just Capabilities/AI) and, in edit mode, the
  target agent, before handing everything to `AgentForm`.

  `{#key name}` around `<AgentForm>` forces a fresh instance (and thus a
  fresh `AgentFormState`) whenever the route's target agent changes —
  App.svelte's router reuses the same lazily-imported component reference
  across an in-app navigation from one `/admin/agents/:name` to another
  (or to `/admin/agents/new`), so without the key a stale
  `AgentFormState` from the previous agent would otherwise persist.
-->
<script lang="ts">
  import { getAgent, getCatalog, listTools } from "$lib/api/agents";
  import { ApiError } from "$lib/api/http";
  import { router } from "$lib/router.svelte";
  import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";

  import AgentForm from "./AgentForm.svelte";

  const name = $derived(router.params.name ?? null);
  const mode = $derived<"create" | "edit">(name ? "edit" : "create");

  let loading = $state(true);
  let error = $state<string | null>(null);
  let agent = $state<BotAgentItem | null>(null);
  let catalog = $state<AdminCatalog | null>(null);
  let tools = $state<Record<string, ToolInfo>>({});

  // Deliberately no reactive `$state` read before the first `await` other
  // than the intentional `name` dependency established in the `$effect`
  // below (AgentsList.svelte's fetch-hygiene comment) — avoids the
  // effect self-retriggering on the writes this function makes.
  async function load(currentName: string | null): Promise<void> {
    loading = true;
    error = null;
    try {
      const [catalogResponse, toolsResponse, agentResponse] = await Promise.all([
        getCatalog(),
        listTools(),
        currentName ? getAgent(currentName) : Promise.resolve(null),
      ]);
      catalog = catalogResponse;
      tools = toolsResponse.tools;
      agent = agentResponse;
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Failed to load the agent form";
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    load(name);
  });
</script>

{#if loading}
  <div class="flex flex-col gap-2" data-testid="agent-form-loading">
    {#each Array(6) as _, i (i)}
      <Skeleton class="h-10 w-full" />
    {/each}
  </div>
{:else if error}
  <Card data-testid="agent-form-retry-card">
    <CardHeader>
      <CardTitle>Unable to load the agent form</CardTitle>
    </CardHeader>
    <CardContent class="flex flex-col gap-3">
      <p class="text-muted-foreground text-sm">{error}</p>
      <Button class="w-fit" onclick={() => load(name)}>Retry</Button>
    </CardContent>
  </Card>
{:else if catalog}
  {#key name}
    <AgentForm {mode} {agent} {catalog} {tools} />
  {/key}
{/if}
