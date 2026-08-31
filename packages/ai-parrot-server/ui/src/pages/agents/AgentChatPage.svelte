<!--
  AgentChatPage (TASK-2597, FEAT-476) — route wrapper for
  `/admin/agents/:name/chat`. Reads `router.params.name`, fetches the
  agent via the same `getAgent()` used by AgentFormPage (GET
  /api/v1/bots/:name) to decide the prompt-library `chatbotId` (database
  agents carry `chatbot_id`; registry agents don't — the library is
  simply hidden for them, per `AgentChat`'s own optional prop), and
  mounts the full (`variant="default"`) vendored `AgentChat` (FEAT-476
  Modules 4-6).

  An unknown agent name (404 from getAgent) renders a not-found state
  with a link back to the agents list, mirroring AgentFormPage's
  loading/retry pattern for every other failure.
-->
<script lang="ts">
  import { getAgent } from "$lib/api/agents";
  import { ApiError } from "$lib/api/http";
  import { router } from "$lib/router.svelte";
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";

  import AgentChat from "$lib/components/agents/AgentChat.svelte";

  const name = $derived(router.params.name ?? null);

  let loading = $state(true);
  let notFound = $state(false);
  let error = $state<string | null>(null);
  let agent = $state<BotAgentItem | null>(null);

  const chatbotId = $derived.by(() => {
    const value = agent ? (agent as Record<string, unknown>).chatbot_id : undefined;
    return typeof value === "string" ? value : undefined;
  });

  // Deliberately no reactive `$state` read before the first `await` other
  // than the intentional `currentName` dependency established in the
  // `$effect` below (AgentsList.svelte's fetch-hygiene comment) — avoids
  // the effect self-retriggering on the writes this function makes.
  async function load(currentName: string | null): Promise<void> {
    loading = true;
    notFound = false;
    error = null;
    agent = null;
    if (!currentName) {
      notFound = true;
      loading = false;
      return;
    }
    try {
      agent = await getAgent(currentName);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        notFound = true;
      } else {
        error = err instanceof ApiError ? err.message : "Failed to load the agent";
      }
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    load(name);
  });

  function backToAgents(): void {
    router.navigate("/admin/agents");
  }
</script>

{#if loading}
  <div class="flex flex-col gap-2" data-testid="agent-chat-loading">
    {#each Array(6) as _, i (i)}
      <Skeleton class="h-10 w-full" />
    {/each}
  </div>
{:else if notFound}
  <Card data-testid="agent-chat-not-found">
    <CardHeader>
      <CardTitle>Agent not found</CardTitle>
    </CardHeader>
    <CardContent class="flex flex-col gap-3">
      <p class="text-muted-foreground text-sm">
        No agent named "{name}" exists.
      </p>
      <Button class="w-fit" onclick={backToAgents}>Back to Agents</Button>
    </CardContent>
  </Card>
{:else if error}
  <Card data-testid="agent-chat-retry-card">
    <CardHeader>
      <CardTitle>Unable to load the agent</CardTitle>
    </CardHeader>
    <CardContent class="flex flex-col gap-3">
      <p class="text-muted-foreground text-sm">{error}</p>
      <Button class="w-fit" onclick={() => load(name)}>Retry</Button>
    </CardContent>
  </Card>
{:else if agent && name}
  <div class="flex h-full min-h-0 flex-col gap-3">
    <div class="flex items-center justify-between gap-3">
      <h1 class="text-lg font-semibold">{name}</h1>
      <Button size="sm" variant="outline" onclick={backToAgents}>Back to Agents</Button>
    </div>
    <div class="min-h-0 flex-1 overflow-hidden rounded-md border border-border">
      {#key name}
        <AgentChat agentId={name} {chatbotId} variant="default" />
      {/key}
    </div>
  </div>
{/if}
