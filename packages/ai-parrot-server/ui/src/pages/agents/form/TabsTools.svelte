<!-- TabsTools (FEAT-593) — plain tools, persisted toolkits, datasets, and MCP servers. -->
<script lang="ts">
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { AgentToolkitsResponse } from "$lib/types/generated/AgentToolkitsResponse";
  import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";
  import { getAgentToolkits, getToolkitSchema } from "$lib/api/studio";
  import AgentMcpPanel from "./AgentMcpPanel.svelte";
  import ToolkitDrawer from "./ToolkitDrawer.svelte";

  let { state, tools, agentName }: { state: AgentFormState; tools: Record<string, ToolInfo>; agentName?: string } = $props();

  let configured = $state<AgentToolkitsResponse | null>(null);
  let drawerSlug = $state<string | null>(null);
  let toolkitStatus = $state<Record<string, boolean>>({});
  const selected = $derived(state.values.tools ?? []);
  const unknownTools = $derived(selected.filter((tool) => !(tool in tools)));
  const toolNames = $derived(Object.keys(tools).sort());
  const readOnly = $derived(configured?.editable === false);
  const configuredSlugs = $derived(
    new Set((configured?.toolkits ?? []).flatMap((toolkit) => typeof toolkit.slug === "string" ? [toolkit.slug] : [])),
  );
  const unavailable = $derived(new Set(configured?.unavailable ?? []));
  const toolkitNames = $derived(toolNames.filter((name) => toolkitStatus[name]));
  const plainToolNames = $derived(toolNames.filter((name) => toolkitStatus[name] === false));

  async function refresh(): Promise<void> {
    if (!agentName) {
      configured = null;
      return;
    }
    try {
      configured = await getAgentToolkits(agentName);
    } catch {
      configured = null;
    }
  }

  async function classifyTools(): Promise<void> {
    const pending = toolNames.filter((name) => toolkitStatus[name] === undefined);
    await Promise.all(
      pending.map(async (slug) => {
        try {
          await getToolkitSchema(slug);
          toolkitStatus = { ...toolkitStatus, [slug]: true };
        } catch {
          toolkitStatus = { ...toolkitStatus, [slug]: false };
        }
      }),
    );
  }

  $effect(() => {
    void refresh();
  });

  $effect(() => {
    void classifyTools();
  });

  function toggleTool(name: string, on: boolean): void {
    state.values.tools = on ? [...selected, name] : selected.filter((tool) => tool !== name);
  }
</script>

<div class="flex flex-col gap-5" data-testid="tabs-tools">
  {#if readOnly}
    <div class="border-warning bg-warning/10 rounded-md border p-3 text-sm" data-testid="tools-readonly-banner">
      {configured?.reason ?? "This agent's tool settings are read-only."}
    </div>
  {/if}

  <section class="flex flex-col gap-2">
    <div>
      <h3 class="font-medium">Tools</h3>
      <p class="text-muted-foreground text-sm">Select individual tools saved with this agent form.</p>
    </div>
    {#each plainToolNames as name (name)}
      <div class="flex items-center justify-between gap-3">
        <Label for={`tool-${name}`}>{tools[name].tool_name}</Label>
        <Switch
          id={`tool-${name}`}
          checked={selected.includes(name)}
          disabled={readOnly || unavailable.has(name)}
          onCheckedChange={(on: boolean) => toggleTool(name, on)}
          data-testid={`tool-switch-${name}`}
        />
      </div>
    {/each}
    {#if unknownTools.length > 0}
      <div class="flex flex-col gap-1" data-testid="tools-unknown-chips">
        <p class="text-muted-foreground text-xs">Selected but not in the current tools catalog:</p>
        {#each unknownTools as name (name)}
          <span class="bg-muted w-fit rounded px-2 py-0.5 text-xs" data-testid={`tool-unknown-${name}`}>{name}</span>
        {/each}
      </div>
    {/if}
  </section>

  <section class="flex flex-col gap-2">
    <div>
      <h3 class="font-medium">Toolkits</h3>
      <p class="text-muted-foreground text-sm">Configure toolkit defaults and secret-backed settings.</p>
    </div>
    {#each toolkitNames as slug (slug)}
      <div class:opacity-50={unavailable.has(slug)} class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2"><span>{tools[slug].tool_name}</span>{#if configuredSlugs.has(slug)}<Badge>Configured</Badge>{/if}</div>
        <Button type="button" variant="outline" size="sm" disabled={!agentName || readOnly || unavailable.has(slug)} onclick={() => (drawerSlug = slug)}>Configure</Button>
      </div>
    {/each}
  </section>

  <section class="flex flex-col gap-2">
    <h3 class="font-medium">Datasets</h3>
    <Button type="button" variant="outline" class="w-fit" disabled={!agentName || readOnly} onclick={() => (drawerSlug = "dataset_manager")}>Configure datasets</Button>
    {#if !agentName}<p class="text-muted-foreground text-xs">Save the agent first to configure datasets and toolkits.</p>{/if}
  </section>

  <section class="flex flex-col gap-2">
    <h3 class="font-medium">MCP servers</h3>
    <AgentMcpPanel {agentName} readonly={readOnly} />
  </section>
</div>

{#if drawerSlug}
  <ToolkitDrawer slug={drawerSlug} {agentName} readonly={readOnly} onclose={() => (drawerSlug = null)} onsaved={refresh} />
{/if}
