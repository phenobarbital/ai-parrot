<!-- AgentMcpPanel (FEAT-593) — agent-level MCP server editor. -->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import StringListEditor from "$lib/components/StringListEditor.svelte";
  import { ApiError } from "$lib/api/http";
  import { getAgentMcpServers, putAgentMcpServers } from "$lib/api/studio";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import type { AgentMCPServerSpec } from "$lib/types/generated/AgentMCPServerSpec";

  let { agentName, readonly = false }: { agentName?: string; readonly?: boolean } = $props();
  let servers = $state<AgentMCPServerSpec[]>([]);
  let error = $state<string | null>(null);
  let saving = $state(false);

  function update(index: number, values: Partial<AgentMCPServerSpec>): void {
    servers = servers.map((server, current) => current === index ? { ...server, ...values } : server);
  }

  function updateParams(index: number, params: Record<string, unknown>): void {
    update(index, { params });
  }

  async function load(): Promise<void> {
    if (!agentName) return;
    try {
      const response = await getAgentMcpServers(agentName);
      servers = (response.servers ?? []) as AgentMCPServerSpec[];
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Unable to load MCP servers";
    }
  }

  async function save(): Promise<void> {
    if (!agentName) return;
    saving = true;
    try {
      const response = await putAgentMcpServers(agentName, servers);
      servers = (response.servers ?? []) as AgentMCPServerSpec[];
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Unable to save MCP servers";
    } finally {
      saving = false;
    }
  }

  $effect(() => { void load(); });
</script>

{#if !agentName}<p class="text-muted-foreground text-xs">Save the agent first to configure MCP servers.</p>
{:else}
  <div class="flex flex-col gap-3" data-testid="agent-mcp-panel">
    {#if error}<p class="text-destructive text-sm">{error}</p>{/if}
    {#each servers as server, index (index)}
      <div class="border-input flex flex-col gap-3 rounded-md border p-3" class:opacity-60={readonly} class:pointer-events-none={readonly}>
        <div class="grid gap-2 sm:grid-cols-2">
          <label><span class="text-sm">Name</span><Input value={server.name} disabled={readonly} oninput={(event) => update(index, { name: event.currentTarget.value })} /></label>
          <label><span class="text-sm">Transport</span><Input value={server.transport ?? "stdio"} disabled={readonly} oninput={(event) => update(index, { transport: event.currentTarget.value })} /></label>
          <label><span class="text-sm">URL</span><Input value={server.url ?? ""} disabled={readonly} oninput={(event) => update(index, { url: event.currentTarget.value || null })} /></label>
          <label><span class="text-sm">Command</span><Input value={server.command ?? ""} disabled={readonly} oninput={(event) => update(index, { command: event.currentTarget.value || null })} /></label>
          <label><span class="text-sm">Description</span><Input value={server.description ?? ""} disabled={readonly} oninput={(event) => update(index, { description: event.currentTarget.value || null })} /></label>
          <label><span class="text-sm">Auth type</span><Input value={server.auth_type ?? ""} disabled={readonly} oninput={(event) => update(index, { auth_type: event.currentTarget.value || null })} /></label>
        </div>
        <StringListEditor id={`mcp-args-${index}`} bind:items={() => server.args ?? [], (args) => update(index, { args })} placeholder="Argument" />
        <StringListEditor id={`mcp-allowed-${index}`} bind:items={() => server.allowed_tools ?? [], (allowed_tools) => update(index, { allowed_tools })} placeholder="Allowed tool" />
        <StringListEditor id={`mcp-blocked-${index}`} bind:items={() => server.blocked_tools ?? [], (blocked_tools) => update(index, { blocked_tools })} placeholder="Blocked tool" />
        <JsonEditor id={`mcp-secrets-${index}`} label="Headers, auth config, and environment (masked)" mode="object" bind:value={() => server.params ?? {}, (params) => updateParams(index, params as Record<string, unknown>)} onvalid={() => undefined} />
        <Button type="button" variant="destructive" class="w-fit" disabled={readonly} onclick={() => (servers = servers.filter((_, current) => current !== index))}>Remove</Button>
      </div>
    {/each}
    <div class="flex gap-2">
      <Button type="button" variant="outline" disabled={readonly} onclick={() => (servers = [...servers, { name: "", transport: "stdio", args: [] }])}>Add server</Button>
      <Button type="button" disabled={readonly || saving} onclick={save}>Save MCP servers</Button>
    </div>
  </div>
{/if}
