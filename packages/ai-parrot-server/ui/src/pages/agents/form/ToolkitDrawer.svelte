<!-- ToolkitDrawer (FEAT-593) — schema-driven persisted toolkit configuration. -->
<script lang="ts">
  import SchemaForm from "$lib/components/schema-form/SchemaForm.svelte";
  import apiClient, { ApiError } from "$lib/api/http";
  import { deleteAgentToolkit, getAgentToolkits, getToolkitOptions, getToolkitSchema, putAgentToolkit, reloadAgent } from "$lib/api/studio";
  import { AppSheet } from "$lib/ui/components";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import type { ToolkitSchemaEnvelope } from "$lib/types/generated/ToolkitSchemaEnvelope";

  let { slug, agentName, readonly = false, onclose, onsaved }: { slug: string; agentName?: string; readonly?: boolean; onclose: () => void; onsaved: () => void | Promise<void> } = $props();

  let open = $state(true);
  let schema = $state<ToolkitSchemaEnvelope | null>(null);
  let params = $state<Record<string, unknown>>({});
  let overridable = $state<string[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let reloadRequired = $state(false);
  let warnings = $state<string[]>([]);
  let error = $state<string | null>(null);
  let persisted = $state(false);

  function message(err: unknown): string {
    return err instanceof ApiError ? err.message : "Unable to update toolkit settings";
  }

  async function load(): Promise<void> {
    if (!agentName) return;
    loading = true;
    error = null;
    try {
      const [envelope, response] = await Promise.all([getToolkitSchema(slug), getAgentToolkits(agentName)]);
      schema = envelope;
      const current = response.toolkits?.find((toolkit) => toolkit.slug === slug);
      if (current) {
        const spec = current as { params?: Record<string, unknown>; user_overridable?: string[] };
        params = spec.params ?? {};
        overridable = spec.user_overridable ?? [];
        persisted = true;
      }
    } catch (err) {
      error = message(err);
    } finally {
      loading = false;
    }
  }

  async function save(): Promise<void> {
    if (!agentName) return;
    saving = true;
    error = null;
    try {
      const result = await putAgentToolkit(agentName, slug, { params, user_overridable: overridable });
      persisted = result.persisted !== false;
      reloadRequired = result.reload_required !== false;
      await onsaved();
    } catch (err) {
      error = message(err);
    } finally {
      saving = false;
    }
  }

  async function remove(): Promise<void> {
    if (!agentName) return;
    saving = true;
    try {
      const result = await deleteAgentToolkit(agentName, slug);
      reloadRequired = result.reload_required !== false;
      await onsaved();
    } catch (err) {
      error = message(err);
    } finally {
      saving = false;
    }
  }

  async function testToolkit(): Promise<void> {
    if (!agentName) return;
    saving = true;
    try {
      await apiClient.post(`/api/v1/astudio/agents/${encodeURIComponent(agentName)}/toolkits`, { slug, params });
    } catch (err) {
      error = message(err);
    } finally {
      saving = false;
    }
  }

  async function reload(): Promise<void> {
    if (!agentName) return;
    try {
      await reloadAgent(agentName);
      reloadRequired = false;
      warnings = [];
    } catch (err) {
      error = message(err);
    }
  }

  $effect(() => { void load(); });
</script>

<AppSheet bind:open title={`Configure ${slug}`} size="lg" onclose={onclose}>
  {#if loading}<p class="text-muted-foreground text-sm">Loading toolkit configuration…</p>
  {:else if error}<p class="text-destructive text-sm" data-testid="toolkit-drawer-error">{error}</p>
  {:else if schema}
    <SchemaForm schema={schema.schema} value={params} {overridable} showOverridable optionsLoader={persisted && agentName ? (param) => getToolkitOptions(agentName, slug, param).then((result) => result.options) : undefined} {readonly} onchange={(value, selected) => { params = value; overridable = selected; }} />
  {/if}
  {#if reloadRequired}
    <div class="bg-warning/10 border-warning mt-4 rounded-md border p-3 text-sm" data-testid="toolkit-reload-required">
      Reload required. <Button type="button" size="sm" onclick={reload}>Reload agent</Button>
      {#each warnings as warning (warning)}<p>{warning}</p>{/each}
    </div>
  {/if}
  {#snippet footer()}
    {#if persisted && !readonly}<Button type="button" variant="destructive" disabled={saving} onclick={remove}>Delete</Button>{/if}
    <Button type="button" variant="outline" disabled={saving || readonly} onclick={testToolkit}>Test</Button>
    <Button type="button" disabled={saving || readonly || !schema} onclick={save}>Save</Button>
  {/snippet}
</AppSheet>
