<!--
  TabsDataMemory (TASK-2587, FEAT-475) — use_vector, vector_store_config,
  reranker_config, parent_searcher_config (JsonEditors),
  context_search_limit, context_score_threshold, memory_type (from
  catalog), memory_config (JsonEditor), max_context_turns,
  use_conversation_history.
-->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";

  let { state, catalog }: { state: AgentFormState; catalog: AdminCatalog } = $props();
</script>

<div class="flex flex-col gap-4" data-testid="tabs-data-memory">
  <div class="flex items-center gap-2">
    <Switch
      id="use_vector"
      checked={state.values.use_vector ?? false}
      onCheckedChange={(v: boolean) => (state.values.use_vector = v)}
      data-testid="field-use_vector"
    />
    <Label for="use_vector">Use vector store</Label>
  </div>

  <JsonEditor
    id="vector_store_config"
    label="Vector store config"
    mode="object"
    bind:value={
      () => state.values.vector_store_config ?? {},
      (v) => (state.values.vector_store_config = v as Record<string, unknown> | null)
    }
  />

  <JsonEditor
    id="reranker_config"
    label="Reranker config"
    mode="object"
    bind:value={
      () => state.values.reranker_config ?? {},
      (v) => (state.values.reranker_config = v as Record<string, unknown> | null)
    }
  />

  <JsonEditor
    id="parent_searcher_config"
    label="Parent searcher config"
    mode="object"
    bind:value={
      () => state.values.parent_searcher_config ?? {},
      (v) => (state.values.parent_searcher_config = v as Record<string, unknown> | null)
    }
  />

  <div class="flex flex-col gap-1.5">
    <Label for="context_search_limit">Context search limit</Label>
    <Input
      id="context_search_limit"
      type="number"
      value={state.values.context_search_limit ?? 10}
      oninput={(e) => (state.values.context_search_limit = Number(e.currentTarget.value))}
      data-testid="field-context_search_limit"
    />
    {#if state.errors.context_search_limit}
      <p class="text-destructive text-xs" data-testid="error-context_search_limit">
        {state.errors.context_search_limit}
      </p>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="context_score_threshold">Context score threshold</Label>
    <Input
      id="context_score_threshold"
      type="number"
      step="0.05"
      value={state.values.context_score_threshold ?? 0.7}
      oninput={(e) => (state.values.context_score_threshold = Number(e.currentTarget.value))}
      data-testid="field-context_score_threshold"
    />
    {#if state.errors.context_score_threshold}
      <p class="text-destructive text-xs" data-testid="error-context_score_threshold">
        {state.errors.context_score_threshold}
      </p>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="memory_type">Memory type</Label>
    <select
      id="memory_type"
      class="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
      value={state.values.memory_type ?? "memory"}
      onchange={(e) =>
        (state.values.memory_type = e.currentTarget.value as typeof state.values.memory_type)}
      data-testid="field-memory_type"
    >
      {#each catalog.memory_types as type (type)}
        <option value={type}>{type}</option>
      {/each}
    </select>
    {#if state.errors.memory_type}
      <p class="text-destructive text-xs" data-testid="error-memory_type">
        {state.errors.memory_type}
      </p>
    {/if}
  </div>

  <JsonEditor
    id="memory_config"
    label="Memory config"
    mode="object"
    bind:value={
      () => state.values.memory_config ?? {},
      (v) => (state.values.memory_config = v as Record<string, unknown> | null)
    }
  />

  <div class="flex flex-col gap-1.5">
    <Label for="max_context_turns">Max context turns</Label>
    <Input
      id="max_context_turns"
      type="number"
      value={state.values.max_context_turns ?? 5}
      oninput={(e) => (state.values.max_context_turns = Number(e.currentTarget.value))}
      data-testid="field-max_context_turns"
    />
    {#if state.errors.max_context_turns}
      <p class="text-destructive text-xs" data-testid="error-max_context_turns">
        {state.errors.max_context_turns}
      </p>
    {/if}
  </div>

  <div class="flex items-center gap-2">
    <Switch
      id="use_conversation_history"
      checked={state.values.use_conversation_history ?? true}
      onCheckedChange={(v: boolean) => (state.values.use_conversation_history = v)}
      data-testid="field-use_conversation_history"
    />
    <Label for="use_conversation_history">Use conversation history</Label>
  </div>
</div>
