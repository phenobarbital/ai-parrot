<!--
  TabsGeneral (TASK-2587, FEAT-475) — chatbot_id (read-only, edit only),
  name (read-only + hint in edit mode, §8 Q3), description, avatar,
  enabled, timezone, language, disclaimer.
-->
<script lang="ts">
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";

  let { state }: { state: AgentFormState } = $props();
</script>

<div class="flex flex-col gap-4" data-testid="tabs-general">
  {#if state.mode === "edit"}
    <div class="flex flex-col gap-1.5">
      <Label for="chatbot_id">Chatbot ID</Label>
      <Input id="chatbot_id" value={state.meta.chatbot_id ?? ""} readonly disabled data-testid="field-chatbot_id" />
    </div>
  {/if}

  <div class="flex flex-col gap-1.5">
    <Label for="name">Name</Label>
    {#if state.mode === "edit"}
      <Input id="name" value={state.values.name ?? ""} readonly disabled data-testid="field-name" />
      <p class="text-muted-foreground text-xs">Name cannot be changed after creation.</p>
    {:else}
      <Input
        id="name"
        value={state.values.name ?? ""}
        oninput={(e) => (state.values.name = e.currentTarget.value)}
        data-testid="field-name"
      />
    {/if}
    {#if state.errors.name}
      <p class="text-destructive text-xs" data-testid="error-name">{state.errors.name}</p>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="description">Description</Label>
    <Input
      id="description"
      value={state.values.description ?? ""}
      oninput={(e) => (state.values.description = e.currentTarget.value || null)}
      data-testid="field-description"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="avatar">Avatar URL</Label>
    <Input
      id="avatar"
      value={state.values.avatar ?? ""}
      oninput={(e) => (state.values.avatar = e.currentTarget.value || null)}
      data-testid="field-avatar"
    />
  </div>

  <div class="flex items-center gap-2">
    <Switch
      id="enabled"
      checked={state.values.enabled ?? true}
      onCheckedChange={(v: boolean) => (state.values.enabled = v)}
      data-testid="field-enabled"
    />
    <Label for="enabled">Enabled</Label>
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="timezone">Timezone</Label>
    <Input
      id="timezone"
      value={state.values.timezone ?? ""}
      oninput={(e) => (state.values.timezone = e.currentTarget.value || null)}
      data-testid="field-timezone"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="language">Language</Label>
    <Input
      id="language"
      value={state.values.language ?? ""}
      oninput={(e) => (state.values.language = e.currentTarget.value || null)}
      data-testid="field-language"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="disclaimer">Disclaimer</Label>
    <Input
      id="disclaimer"
      value={state.values.disclaimer ?? ""}
      oninput={(e) => (state.values.disclaimer = e.currentTarget.value || null)}
      data-testid="field-disclaimer"
    />
  </div>
</div>
