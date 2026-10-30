<!--
  TabsCapabilities (TASK-2587, FEAT-475) — tools_enabled,
  auto_tool_detection, tool_threshold (Slider), operation_mode (from catalog),
  use_kb, kb (JsonEditor, array
  mode), custom_kbs (StringListEditor, catalog.knowledge_bases class paths
  as suggestions).
-->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import StringListEditor from "$lib/components/StringListEditor.svelte";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Slider } from "$lib/ui/internal/shadcn/ui/slider/index.js";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";

  let {
    state,
    catalog,
  }: {
    state: AgentFormState;
    catalog: AdminCatalog;
  } = $props();

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

  <fieldset class="flex flex-col gap-3 rounded-md border p-3" data-testid="group-suggestions">
    <legend class="px-1 text-sm font-medium">Follow-up suggestions</legend>
    <div class="flex items-center gap-2">
      <Switch
        id="enable_suggestions"
        checked={state.values.enable_suggestions ?? false}
        onCheckedChange={(v: boolean) => (state.values.enable_suggestions = v)}
        data-testid="field-enable_suggestions"
      />
      <Label for="enable_suggestions">Suggestion chips</Label>
    </div>

    <div class="flex items-center gap-2">
      <Switch
        id="suggest_followups"
        checked={state.values.suggest_followups ?? false}
        onCheckedChange={(v: boolean) => (state.values.suggest_followups = v)}
        data-testid="field-suggest_followups"
      />
      <Label for="suggest_followups">LLM follow-up suggestions</Label>
    </div>

    <div class="flex flex-col gap-1.5">
      <Label for="suggestion_timeout_s">Suggestion timeout (seconds)</Label>
      <Input
        id="suggestion_timeout_s"
        type="number"
        min="0"
        step="0.5"
        value={state.values.suggestion_timeout_s ?? 4}
        disabled={!(state.values.suggest_followups ?? false)}
        oninput={(e) => (state.values.suggestion_timeout_s = Number(e.currentTarget.value))}
        data-testid="field-suggestion_timeout_s"
      />
      {#if state.errors.suggestion_timeout_s}
        <p class="text-destructive text-xs" data-testid="error-suggestion_timeout_s">
          {state.errors.suggestion_timeout_s}
        </p>
      {/if}
    </div>

    <div class="flex flex-col gap-1.5">
      <Label for="max_suggestions">Maximum suggestions</Label>
      <Input
        id="max_suggestions"
        type="number"
        min="0"
        step="1"
        value={state.values.max_suggestions ?? 6}
        oninput={(e) => (state.values.max_suggestions = Number(e.currentTarget.value))}
        data-testid="field-max_suggestions"
      />
      {#if state.errors.max_suggestions}
        <p class="text-destructive text-xs" data-testid="error-max_suggestions">
          {state.errors.max_suggestions}
        </p>
      {/if}
    </div>

    <div class="flex flex-col gap-1.5">
      <Label for="suggestion_model">Suggestion model (optional)</Label>
      <Input
        id="suggestion_model"
        value={state.values.suggestion_model ?? ""}
        disabled={!(state.values.suggest_followups ?? false)}
        oninput={(e) => (state.values.suggestion_model = e.currentTarget.value || null)}
        data-testid="field-suggestion_model"
      />
    </div>
  </fieldset>

  <JsonEditor
    id="kb"
    label="Knowledge base facts"
    mode="array"
    hint="A list of KB fact objects."
    bind:value={
      () => state.values.kb ?? [],
      (v) => (state.values.kb = v as Record<string, unknown>[] | null)
    }
    onvalid={(valid: boolean) => state.setJsonValid("kb", valid)}
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
