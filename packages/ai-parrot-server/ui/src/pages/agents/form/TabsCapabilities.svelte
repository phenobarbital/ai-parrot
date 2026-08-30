<!--
  TabsCapabilities (TASK-2587, FEAT-475) — tools_enabled,
  auto_tool_detection, tool_threshold (Slider), tools (checkbox list from
  GET /api/v1/agent_tools + StringListEditor fallback for names the
  current catalog doesn't know about — those must remain, never silently
  dropped), operation_mode (from catalog), use_kb, kb (JsonEditor, array
  mode), custom_kbs (StringListEditor, catalog.knowledge_bases class paths
  as suggestions).
-->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import StringListEditor from "$lib/components/StringListEditor.svelte";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
  import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";
  import { Checkbox } from "$lib/ui/internal/shadcn/ui/checkbox/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Slider } from "$lib/ui/internal/shadcn/ui/slider/index.js";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";

  let {
    state,
    catalog,
    tools,
  }: {
    state: AgentFormState;
    catalog: AdminCatalog;
    tools: Record<string, ToolInfo>;
  } = $props();

  const knownToolNames = $derived(Object.keys(tools).sort());
  const selectedTools = $derived(state.values.tools ?? []);
  // Selected tool names absent from the current catalog — surfaced, never
  // silently dropped (e.g. a tool a plugin package removed since save).
  const unknownTools = $derived(selectedTools.filter((t) => !(t in tools)));

  function toggleTool(name: string, checked: boolean): void {
    const current = state.values.tools ?? [];
    state.values.tools = checked ? [...current, name] : current.filter((t) => t !== name);
  }

  const kbSuggestions = $derived(catalog.knowledge_bases.map((kb) => kb.class_path));
</script>

<div class="flex flex-col gap-4" data-testid="tabs-capabilities">
  <div class="flex items-center gap-2">
    <Switch
      id="tools_enabled"
      checked={state.values.tools_enabled ?? true}
      onCheckedChange={(v: boolean) => (state.values.tools_enabled = v)}
      data-testid="field-tools_enabled"
    />
    <Label for="tools_enabled">Tools enabled</Label>
  </div>

  <div class="flex items-center gap-2">
    <Switch
      id="auto_tool_detection"
      checked={state.values.auto_tool_detection ?? true}
      onCheckedChange={(v: boolean) => (state.values.auto_tool_detection = v)}
      data-testid="field-auto_tool_detection"
    />
    <Label for="auto_tool_detection">Auto tool detection</Label>
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="tool_threshold">Tool threshold: {state.values.tool_threshold ?? 0}</Label>
    <Slider
      id="tool_threshold"
      min={0}
      max={1}
      step={0.05}
      value={state.values.tool_threshold ?? 0.7}
      onValueChange={(v: number) => (state.values.tool_threshold = v)}
      data-testid="field-tool_threshold"
    />
    {#if state.errors.tool_threshold}
      <p class="text-destructive text-xs" data-testid="error-tool_threshold">
        {state.errors.tool_threshold}
      </p>
    {/if}
  </div>

  <div class="flex flex-col gap-2">
    <Label>Tools</Label>
    <div class="flex flex-col gap-1.5" data-testid="tools-checkbox-list">
      {#each knownToolNames as name (name)}
        <div class="flex items-center gap-2">
          <Checkbox
            id={`tool-${name}`}
            checked={selectedTools.includes(name)}
            onCheckedChange={(v: boolean) => toggleTool(name, v)}
            data-testid={`tool-checkbox-${name}`}
          />
          <Label for={`tool-${name}`}>{tools[name].tool_name}</Label>
        </div>
      {/each}
    </div>
    {#if unknownTools.length > 0}
      <div class="flex flex-col gap-1" data-testid="tools-unknown-chips">
        <p class="text-muted-foreground text-xs">
          Selected but not in the current tools catalog:
        </p>
        {#each unknownTools as name (name)}
          <span class="bg-muted w-fit rounded px-2 py-0.5 text-xs" data-testid={`tool-unknown-${name}`}>
            {name}
          </span>
        {/each}
      </div>
    {/if}
    <StringListEditor
      id="tools-manual"
      placeholder="Add a tool name not listed above…"
      bind:items={
        () => state.values.tools ?? [],
        (v) => (state.values.tools = v)
      }
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="operation_mode">Operation mode</Label>
    <select
      id="operation_mode"
      class="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
      value={state.values.operation_mode ?? "adaptive"}
      onchange={(e) =>
        (state.values.operation_mode = e.currentTarget.value as typeof state.values.operation_mode)}
      data-testid="field-operation_mode"
    >
      {#each catalog.operation_modes as mode (mode)}
        <option value={mode}>{mode}</option>
      {/each}
    </select>
    {#if state.errors.operation_mode}
      <p class="text-destructive text-xs" data-testid="error-operation_mode">
        {state.errors.operation_mode}
      </p>
    {/if}
  </div>

  <div class="flex items-center gap-2">
    <Switch
      id="use_kb"
      checked={state.values.use_kb ?? false}
      onCheckedChange={(v: boolean) => (state.values.use_kb = v)}
      data-testid="field-use_kb"
    />
    <Label for="use_kb">Use knowledge base</Label>
  </div>

  <JsonEditor
    id="kb"
    label="Knowledge base facts"
    mode="array"
    hint="A list of KB fact objects."
    bind:value={
      () => state.values.kb ?? [],
      (v) => (state.values.kb = v as Record<string, unknown>[] | null)
    }
  />

  <div class="flex flex-col gap-1.5">
    <Label for="custom_kbs">Custom knowledge base classes</Label>
    <StringListEditor
      id="custom_kbs"
      suggestions={kbSuggestions}
      bind:items={
        () => state.values.custom_kbs ?? [],
        (v) => (state.values.custom_kbs = v)
      }
    />
  </div>
</div>
