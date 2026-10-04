<!-- MyToolkitSettings (FEAT-593) — the user's own overrides of operator-allowed toolkit params.

     Slug source (TASK-3666 Implementation Notes): the primary source is `getAgentToolkits`
     (the agent's configured toolkits, owner-gated). When that call is denied (403 — the caller
     is not the agent owner) there is no other discovery endpoint available to this component, so
     the tab degrades to the empty state rather than guessing at a toolkit list. -->
<script lang="ts">
  import { onMount } from "svelte";
  import Icon from "@iconify/svelte";
  import SchemaForm from "$lib/components/schema-form/SchemaForm.svelte";
  import {
    deleteMyToolkitOverride,
    getAgentToolkits,
    getMyToolkitOverride,
    getToolkitSchema,
    putMyToolkitOverride,
  } from "$lib/api/studio";
  import { toastStore } from "$lib/stores/toast.svelte";

  let { agentId }: { agentId: string } = $props();

  type JsonSchema = Record<string, unknown>;

  type MyToolkitOverride = {
    slug: string;
    overridable: string[];
    params: Record<string, unknown>;
    configured: boolean;
  };

  type Entry = {
    slug: string;
    overridable: string[];
    schema: JsonSchema;
    value: Record<string, unknown>;
    status: string | null;
  };

  let entries = $state<Entry[]>([]);
  let isLoading = $state(true);
  let savingSlug = $state<string | null>(null);

  onMount(async () => {
    await load();
  });

  /** Restrict a toolkit's config schema to only its currently overridable properties. */
  function filterSchema(schema: JsonSchema, overridable: string[]): JsonSchema {
    const properties = (schema.properties as JsonSchema | undefined) ?? {};
    const filteredProperties: JsonSchema = {};
    for (const key of overridable) {
      if (key in properties) {
        filteredProperties[key] = properties[key];
      }
    }
    return {
      ...schema,
      properties: filteredProperties,
      required: [],
    };
  }

  async function load(): Promise<void> {
    isLoading = true;
    const built: Entry[] = [];
    try {
      const { toolkits } = await getAgentToolkits(agentId);
      const slugs = (toolkits ?? [])
        .map((spec) => (spec as { slug?: string }).slug)
        .filter((slug): slug is string => Boolean(slug));

      for (const slug of slugs) {
        try {
          const override = (await getMyToolkitOverride(agentId, slug)) as unknown as MyToolkitOverride;
          const overridable = override.overridable ?? [];
          if (overridable.length === 0) {
            continue;
          }
          const { schema } = await getToolkitSchema(slug);
          built.push({
            slug,
            overridable,
            schema: filterSchema(schema, overridable),
            value: { ...(override.params ?? {}) },
            status: null,
          });
        } catch (error) {
          console.error(`Failed to load your "${slug}" settings:`, error);
        }
      }
    } catch (error) {
      // Owner-gated list (403 for non-owners) or any other failure: no editable
      // toolkits can be shown to this caller — degrade to the empty state.
      console.error(`Failed to load toolkits for agent "${agentId}":`, error);
    } finally {
      entries = built;
      isLoading = false;
    }
  }

  async function save(entry: Entry): Promise<void> {
    savingSlug = entry.slug;
    entry.status = null;
    try {
      await putMyToolkitOverride(agentId, entry.slug, { params: entry.value });
      entry.status = "Saved — applies from your next message.";
      toastStore.success(`Saved your "${entry.slug}" settings.`);
    } catch (error: any) {
      console.error(`Failed to save your "${entry.slug}" settings:`, error);
      toastStore.error(error?.message || `Failed to save your "${entry.slug}" settings.`);
    } finally {
      savingSlug = null;
    }
  }

  async function reset(entry: Entry): Promise<void> {
    savingSlug = entry.slug;
    entry.status = null;
    try {
      await deleteMyToolkitOverride(agentId, entry.slug);
      entry.value = {};
      entry.status = "Reset — applies from your next message.";
      toastStore.success(`Reset your "${entry.slug}" settings.`);
    } catch (error: any) {
      console.error(`Failed to reset your "${entry.slug}" settings:`, error);
      toastStore.error(error?.message || `Failed to reset your "${entry.slug}" settings.`);
    } finally {
      savingSlug = null;
    }
  }
</script>

<div class="flex flex-col gap-3 pt-1">
  <div class="flex items-center gap-2">
    <div
      class="flex h-8 w-8 items-center justify-center rounded-md bg-amber-100 text-amber-600 dark:bg-amber-900 dark:text-amber-400"
    >
      <Icon icon="mdi:account-cog" class="h-4 w-4" />
    </div>
    <div class="flex flex-col">
      <span class="text-sm font-semibold text-slate-700 dark:text-slate-200">
        My tool settings
      </span>
      <span class="text-xs text-slate-500 dark:text-slate-400">
        Your own overrides of the params this agent's operator allows you to change
      </span>
    </div>
  </div>

  {#if isLoading}
    <div class="flex items-center justify-center py-6 opacity-50">
      <span class="loading loading-spinner w-5 h-5"></span>
      <span class="ml-2 text-sm">Loading your tool settings...</span>
    </div>
  {:else if entries.length === 0}
    <div
      class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-200 dark:border-slate-700 py-8 opacity-60"
    >
      <p class="text-sm text-slate-500 dark:text-slate-400">
        No tool settings you can change for this agent
      </p>
    </div>
  {:else}
    <div class="flex flex-col gap-3">
      {#each entries as entry (entry.slug)}
        <div
          class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <div class="flex items-center justify-between gap-2 mb-3">
            <span class="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {entry.slug}
            </span>
            <div class="flex items-center gap-2">
              <button
                class="btn btn-ghost btn-sm"
                onclick={() => reset(entry)}
                disabled={savingSlug === entry.slug}
              >
                Reset
              </button>
              <button
                class="btn btn-primary btn-sm"
                onclick={() => save(entry)}
                disabled={savingSlug === entry.slug}
              >
                {#if savingSlug === entry.slug}
                  <span class="loading loading-spinner w-3 h-3"></span>
                {/if}
                Save
              </button>
            </div>
          </div>

          <div class="flex flex-col gap-2">
            <SchemaForm
              schema={entry.schema}
              value={entry.value}
              onchange={(v) => (entry.value = v)}
            />
          </div>

          {#if entry.status}
            <p class="mt-2 text-xs font-medium text-green-600 dark:text-green-400">
              {entry.status}
            </p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
