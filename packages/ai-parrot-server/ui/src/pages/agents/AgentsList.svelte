<!--
  AgentsList (TASK-2530) — read-only agents table over GET /api/v1/bots,
  absorbing the list-view design from
  sdd/proposals/ui-agent-management.brainstorm.md:104-107. Route
  /admin/agents (wired via pages/Agents.svelte).

  Establishes the module pattern for future feature modules: page under
  pages/<module>/, nav entry already present (TASK-2528's registry), data
  via generated types + the shared API client.

  NO create/edit/delete affordances anywhere — read-only by design (next
  spec owns agent CRUD).

  Implementer's-choice deviations (Codebase Contract explicitly allows
  these — "SimpleTable... or a plain <table>... implementer's choice"):
   - Table: a plain `<table>` with token classes, not a copied SimpleTable
     wrapper — no such wrapper exists yet in this scaffold.
   - Source filter: a 3-way Button toggle group (All/Database/Registry)
     instead of the vendored bits-ui-backed Select — avoids that
     primitive's floating-ui positioning machinery in the jsdom test
     environment (not needed here: only 3 fixed options, no search).
-->
<script lang="ts">
  import apiClient, { ApiError } from "$lib/api/http";
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import type { BotsListResponse } from "$lib/types/generated/BotsListResponse";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";
  import AgentDetail from "./AgentDetail.svelte";

  type SourceFilter = "all" | "database" | "registry";

  let agents = $state<BotAgentItem[] | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let search = $state("");
  let sourceFilter = $state<SourceFilter>("all");

  let detailOpen = $state(false);
  let selectedAgent = $state<BotAgentItem | null>(null);

  // Deliberately no reactive `$state` reads before the first `await` —
  // see Dashboard.svelte's fetchStatus() for why (avoids the polling
  // $effect re-triggering itself on every state write this makes; this
  // page doesn't poll, but the same hygiene keeps the one-shot fetch
  // dependency-free too).
  async function fetchAgents(): Promise<void> {
    loading = true;
    try {
      const { data } = await apiClient.get<BotsListResponse>("/api/v1/bots");
      agents = data.agents;
      error = null;
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Failed to load agents";
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    fetchAgents();
  });

  function fieldOf(agent: BotAgentItem, key: string): string {
    const value = (agent as Record<string, unknown>)[key];
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  const filtered = $derived.by(() => {
    if (!agents) return [];
    const query = search.trim().toLowerCase();
    return agents.filter((agent) => {
      if (sourceFilter !== "all" && agent.source !== sourceFilter) return false;
      if (!query) return true;
      const name = fieldOf(agent, "name").toLowerCase();
      const description = fieldOf(agent, "description").toLowerCase();
      return name.includes(query) || description.includes(query);
    });
  });

  function openDetail(agent: BotAgentItem): void {
    selectedAgent = agent;
    detailOpen = true;
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-wrap items-center gap-3">
    <Input
      placeholder="Search by name or description…"
      bind:value={search}
      class="max-w-xs"
      aria-label="Search agents"
    />
    <div class="flex gap-2" role="group" aria-label="Filter by source">
      {#each [["all", "All"], ["database", "Database"], ["registry", "Registry"]] as [value, label] (value)}
        <Button
          size="sm"
          variant={sourceFilter === value ? "default" : "outline"}
          onclick={() => (sourceFilter = value as SourceFilter)}
          aria-pressed={sourceFilter === value}
        >
          {label}
        </Button>
      {/each}
    </div>
  </div>

  {#if loading && agents === null}
    <div class="flex flex-col gap-2" data-testid="agents-loading">
      {#each Array(4) as _, i (i)}
        <Skeleton class="h-10 w-full" />
      {/each}
    </div>
  {:else if error && agents === null}
    <Card data-testid="agents-retry-card">
      <CardHeader>
        <CardTitle>Unable to load agents</CardTitle>
      </CardHeader>
      <CardContent class="flex flex-col gap-3">
        <p class="text-muted-foreground text-sm">{error}</p>
        <Button class="w-fit" onclick={() => fetchAgents()}>Retry</Button>
      </CardContent>
    </Card>
  {:else if agents && agents.length === 0}
    <Card data-testid="agents-empty-state">
      <CardContent class="text-muted-foreground py-8 text-center text-sm">
        No agents found.
      </CardContent>
    </Card>
  {:else if agents}
    <div class="border-border overflow-x-auto rounded-md border">
      <table class="w-full text-sm">
        <thead class="bg-muted text-muted-foreground">
          <tr>
            <th class="px-3 py-2 text-left font-medium">Name</th>
            <th class="px-3 py-2 text-left font-medium">Description</th>
            <th class="px-3 py-2 text-left font-medium">Role</th>
            <th class="px-3 py-2 text-left font-medium">Source</th>
            <th class="px-3 py-2 text-left font-medium">Enabled</th>
          </tr>
        </thead>
        <tbody>
          {#each filtered as agent (agent.name + agent.source)}
            <tr
              class="border-border hover:bg-accent/50 cursor-pointer border-t"
              onclick={() => openDetail(agent)}
              data-testid={`agent-row-${agent.name}`}
            >
              <td class="px-3 py-2 font-medium">{agent.name}</td>
              <td class="text-muted-foreground max-w-xs truncate px-3 py-2">
                {fieldOf(agent, "description")}
              </td>
              <td class="px-3 py-2">{fieldOf(agent, "role")}</td>
              <td class="px-3 py-2">
                <Badge variant={agent.source === "database" ? "default" : "secondary"}>
                  {agent.source}
                </Badge>
              </td>
              <td class="px-3 py-2">
                {#if (agent as Record<string, unknown>).enabled === undefined}
                  —
                {:else if (agent as Record<string, unknown>).enabled}
                  Yes
                {:else}
                  No
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if filtered.length === 0}
      <p class="text-muted-foreground text-sm">No agents match the current filters.</p>
    {/if}
  {/if}
</div>

<AgentDetail agent={selectedAgent} bind:open={detailOpen} />
