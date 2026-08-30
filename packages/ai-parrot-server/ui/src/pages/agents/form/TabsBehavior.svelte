<!--
  TabsBehavior (TASK-2587, FEAT-475) — role, goal, backstory, rationale,
  capabilities, pre_instructions[], system/human prompt templates,
  prompt_config (JsonEditor).
-->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import StringListEditor from "$lib/components/StringListEditor.svelte";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Textarea } from "$lib/ui/internal/shadcn/ui/textarea/index.js";

  let { state }: { state: AgentFormState } = $props();
</script>

<div class="flex flex-col gap-4" data-testid="tabs-behavior">
  <div class="flex flex-col gap-1.5">
    <Label for="role">Role</Label>
    <Input
      id="role"
      value={state.values.role ?? ""}
      oninput={(e) => (state.values.role = e.currentTarget.value || null)}
      data-testid="field-role"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="goal">Goal</Label>
    <Textarea
      id="goal"
      value={state.values.goal ?? ""}
      oninput={(e) => (state.values.goal = e.currentTarget.value)}
      data-testid="field-goal"
    />
    {#if state.errors.goal}
      <p class="text-destructive text-xs" data-testid="error-goal">{state.errors.goal}</p>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="backstory">Backstory</Label>
    <Textarea
      id="backstory"
      value={state.values.backstory ?? ""}
      oninput={(e) => (state.values.backstory = e.currentTarget.value)}
      data-testid="field-backstory"
    />
    {#if state.errors.backstory}
      <p class="text-destructive text-xs" data-testid="error-backstory">{state.errors.backstory}</p>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="rationale">Rationale</Label>
    <Textarea
      id="rationale"
      value={state.values.rationale ?? ""}
      oninput={(e) => (state.values.rationale = e.currentTarget.value)}
      data-testid="field-rationale"
    />
    {#if state.errors.rationale}
      <p class="text-destructive text-xs" data-testid="error-rationale">{state.errors.rationale}</p>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="capabilities">Capabilities</Label>
    <Textarea
      id="capabilities"
      value={state.values.capabilities ?? ""}
      oninput={(e) => (state.values.capabilities = e.currentTarget.value || null)}
      data-testid="field-capabilities"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="pre_instructions">Pre-instructions</Label>
    <StringListEditor
      id="pre_instructions"
      bind:items={
        () => state.values.pre_instructions ?? [],
        (v) => (state.values.pre_instructions = v)
      }
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="system_prompt_template">System prompt template</Label>
    <Textarea
      id="system_prompt_template"
      value={state.values.system_prompt_template ?? ""}
      oninput={(e) => (state.values.system_prompt_template = e.currentTarget.value || null)}
      data-testid="field-system_prompt_template"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="human_prompt_template">Human prompt template</Label>
    <Textarea
      id="human_prompt_template"
      value={state.values.human_prompt_template ?? ""}
      oninput={(e) => (state.values.human_prompt_template = e.currentTarget.value || null)}
      data-testid="field-human_prompt_template"
    />
  </div>

  <JsonEditor
    id="prompt_config"
    label="Prompt config"
    mode="object"
    hint="Declarative prompt-layer configuration (preset, remove, add, customize)."
    bind:value={
      () => state.values.prompt_config ?? {},
      (v) => (state.values.prompt_config = v as Record<string, unknown> | null)
    }
  />
</div>
