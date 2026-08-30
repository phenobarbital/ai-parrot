<!--
  TabsAdvanced (TASK-2587, FEAT-475) — bot_class (plain text input,
  default "BasicBot") and permissions (JsonEditor, mode "any" — dict or
  list of rule dicts per BotModel.permissions' dual shape).
-->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";

  let { state }: { state: AgentFormState } = $props();
</script>

<div class="flex flex-col gap-4" data-testid="tabs-advanced">
  <div class="flex flex-col gap-1.5">
    <Label for="bot_class">Bot class</Label>
    <Input
      id="bot_class"
      value={state.values.bot_class ?? "BasicBot"}
      oninput={(e) => (state.values.bot_class = e.currentTarget.value || null)}
      data-testid="field-bot_class"
    />
    <p class="text-muted-foreground text-xs">
      Bot class path, e.g. "parrot.bots.unified.UnifiedBot".
    </p>
  </div>

  <JsonEditor
    id="permissions"
    label="Permissions"
    mode="any"
    hint="A permissions dict, or a list of rule objects."
    bind:value={
      () => state.values.permissions ?? {},
      (v) => (state.values.permissions = v as Record<string, unknown> | Record<string, unknown>[] | null)
    }
    onvalid={(valid: boolean) => state.setJsonValid("permissions", valid)}
  />
</div>
