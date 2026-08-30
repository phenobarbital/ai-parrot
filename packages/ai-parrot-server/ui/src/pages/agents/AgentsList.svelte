<!--
  AgentsList (TASK-2530; create/edit/delete affordances added TASK-2588,
  FEAT-475) — agents table over GET /api/v1/bots. Route /admin/agents
  (wired via pages/Agents.svelte).

  Establishes the module pattern for future feature modules: page under
  pages/<module>/, nav entry already present (TASK-2528's registry), data
  via generated types + the shared API client.

  Mutating affordances (Create, per-row Edit/Delete, "Show disabled") are
  database-row-only — registry rows (`source === "registry"`) stay
  read-only, unchanged from FEAT-468 (spec: registry agents are managed
  outside the Admin UI).

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
  import { listAgents } from "$lib/api/agents";
  import { ApiError } from "$lib/api/http";
  import { router } from "$lib/router.svelte";
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";

  import AgentDetail from "./AgentDetail.svelte";
  import DeleteAgentDialog from "./DeleteAgentDialog.svelte";

  type SourceFilter = "all" | "database" | "registry";

  let agents = $state<BotAgentItem[] | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let search = $state("");
  let sourceFilter = $state<SourceFilter>("all");
  let showDisabled = $state(false);

  let detailOpen = $state(false);
  let selectedAgent = $state<BotAgentItem | null>(null);

  let deleteOpen = $state(false);
  let deleteTarget = $state<BotAgentItem | null>(null);

  // Deliberately no reactive `$state` read before the first `await` other
  // than the intentional `showDisabled` dependency (read as part of the
  // `listAgents({...})` call arguments below) — see Dashboard.svelte's
  // fetchStatus() for why (avoids the effect re-triggering itself on
  // every state write this function makes).
  async function fetchAgents(): Promise<void> {
    loading = true;
    try {
      const data = await listAgents({ includeDisabled: showDisabled });
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

  function goCreate(): void {
    router.navigate("/admin/agents/new");
  }

  function goEdit(agent: BotAgentItem, e: MouseEvent): void {
    e.stopPropagation();
    router.navigate(`/admin/agents/${encodeURIComponent(agent.name)}`);
  }

  function openDelete(agent: BotAgentItem, e: MouseEvent): void {
    e.stopPropagation();
    deleteTarget = agent;
    deleteOpen = true;
  }

  function handleDeleted(): void {
    fetchAgents();
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
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
      <div class="flex items-center gap-2">
        <Switch
          id="show-disabled"
          checked={showDisabled}
          onCheckedChange={(v: boolean) => (showDisabled = v)}
          data-testid="show-disabled-toggle"
        />
        <Label for="show-disabled">Show disabled</Label>
      </div>
    </div>
    <Button onclick={goCreate} data-testid="create-agent-button">Create Agent</Button>
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
            <th class="px-3 py-2 text-left font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each filtered as agent (agent.name + agent.source)}
            {@const isDisabledRow = (agent as Record<string, unknown>).enabled === false}
            <tr
              class="border-border hover:bg-accent/50 cursor-pointer border-t"
              class:opacity-60={isDisabledRow}
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
                {:else if isDisabledRow}
                  <Badge variant="secondary" data-testid={`agent-disabled-badge-${agent.name}`}>
                    disabled
                  </Badge>
                {:else}
                  Yes
                {/if}
              </td>
              <td class="px-3 py-2">
                {#if agent.source === "database"}
                  <div class="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onclick={(e: MouseEvent) => goEdit(agent, e)}
                      data-testid={`agent-edit-${agent.name}`}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onclick={(e: MouseEvent) => openDelete(agent, e)}
                      data-testid={`agent-delete-${agent.name}`}
                    >
                      Delete
                    </Button>
                  </div>
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
<DeleteAgentDialog agent={deleteTarget} bind:open={deleteOpen} ondeleted={handleDeleted} />
