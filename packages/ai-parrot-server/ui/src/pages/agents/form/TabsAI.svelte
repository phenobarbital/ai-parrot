<!--
  TabsAI (TASK-2587, FEAT-475) — llm (from catalog.llm_providers, tolerant
  of an alias not in the list — provider aliases per spec §7), plus
  model/temperature/max_tokens/top_p/top_k convenience fields that read
  and write into the same `model_config` dict the raw JsonEditor below
  edits directly, so both views stay in sync.
-->
<script lang="ts">
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { Slider } from "$lib/ui/internal/shadcn/ui/slider/index.js";

  let { state, catalog }: { state: AgentFormState; catalog: AdminCatalog } = $props();

  function modelConfig(): Record<string, unknown> {
    return (state.values.model_config as Record<string, unknown> | null) ?? {};
  }

  function setModelConfigField(key: string, value: unknown): void {
    const next = { ...modelConfig() };
    if (value === undefined || value === null || value === "") {
      delete next[key];
    } else {
      next[key] = value;
    }
    state.values.model_config = next;
  }

  function numberField(key: string): number | undefined {
    const v = modelConfig()[key];
    return typeof v === "number" ? v : undefined;
  }

  const modelValue = $derived(
    (modelConfig().model as string | undefined) ?? (modelConfig().model_name as string | undefined) ?? "",
  );

  // llm may hold a provider alias not present in catalog.llm_providers
  // (§7: SUPPORTED_CLIENTS has many aliases for the same class) — the
  // stored value is shown even if it's not one of the option elements.
  const llmOptions = $derived.by(() => {
    const opts = [...catalog.llm_providers];
    if (state.values.llm && !opts.includes(state.values.llm)) {
      opts.push(state.values.llm);
    }
    return opts;
  });
</script>

<div class="flex flex-col gap-4" data-testid="tabs-ai">
  <div class="flex flex-col gap-1.5">
    <Label for="llm">LLM provider</Label>
    <select
      id="llm"
      class="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
      value={state.values.llm ?? ""}
      onchange={(e) => (state.values.llm = e.currentTarget.value || null)}
      data-testid="field-llm"
    >
      {#each llmOptions as provider (provider)}
        <option value={provider}>{provider}</option>
      {/each}
    </select>
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="model">Model</Label>
    <Input
      id="model"
      value={modelValue}
      oninput={(e) => setModelConfigField("model", e.currentTarget.value || undefined)}
      data-testid="field-model"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="temperature">Temperature: {numberField("temperature") ?? 0}</Label>
    <Slider
      id="temperature"
      min={0}
      max={2}
      step={0.1}
      value={numberField("temperature") ?? 0}
      onValueChange={(v: number) => setModelConfigField("temperature", v)}
      data-testid="field-temperature"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="max_tokens">Max tokens</Label>
    <Input
      id="max_tokens"
      type="number"
      value={numberField("max_tokens") ?? ""}
      oninput={(e) => {
        const raw = e.currentTarget.value;
        setModelConfigField("max_tokens", raw === "" ? undefined : Number(raw));
      }}
      data-testid="field-max_tokens"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="top_p">top_p</Label>
    <Input
      id="top_p"
      type="number"
      step="0.01"
      value={numberField("top_p") ?? ""}
      oninput={(e) => {
        const raw = e.currentTarget.value;
        setModelConfigField("top_p", raw === "" ? undefined : Number(raw));
      }}
      data-testid="field-top_p"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="top_k">top_k</Label>
    <Input
      id="top_k"
      type="number"
      value={numberField("top_k") ?? ""}
      oninput={(e) => {
        const raw = e.currentTarget.value;
        setModelConfigField("top_k", raw === "" ? undefined : Number(raw));
      }}
      data-testid="field-top_k"
    />
  </div>

  <JsonEditor
    id="model_config"
    label="Raw model config"
    mode="object"
    hint="Full model_config JSON — the fields above edit the same keys."
    bind:value={
      () => state.values.model_config ?? {},
      (v) => (state.values.model_config = v as Record<string, unknown> | null)
    }
    onvalid={(valid: boolean) => state.setJsonValid("model_config", valid)}
  />
</div>
