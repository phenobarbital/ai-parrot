<!-- SchemaForm (FEAT-593) — renders a Draft 2020-12 object schema; no toolkit-specific code. -->
<script lang="ts">
  import type { ConfigOption } from "$lib/types/generated/ConfigOption";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.ts";
  import { Textarea } from "$lib/ui/internal/shadcn/ui/textarea/index.ts";
  import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.ts";
  import { Checkbox } from "$lib/ui/internal/shadcn/ui/checkbox/index.ts";
  import { Slider } from "$lib/ui/internal/shadcn/ui/slider/index.ts";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.ts";
  import { AppTooltip } from "$lib/ui/components/AppTooltip.svelte";
  import JsonEditor from "$lib/components/JsonEditor.svelte";
  import StringListEditor from "$lib/components/StringListEditor.svelte";
  import SchemaForm from "./SchemaForm.svelte";

  type JsonSchema = Record<string, unknown>;

  let {
    schema,
    value,
    overridable = [],
    showOverridable = false,
    optionsLoader,
    readonly = false,
    onchange,
    root,
  }: {
    schema: JsonSchema;
    value: Record<string, unknown>;
    overridable?: string[];
    showOverridable?: boolean;
    optionsLoader?: (param: string) => Promise<ConfigOption[]>;
    readonly?: boolean;
    onchange: (value: Record<string, unknown>, overridable: string[]) => void;
    root?: JsonSchema; // $defs holder for recursive sub-forms
  } = $props();

  const defs = $derived((root ?? schema).$defs ?? {});
  const props = $derived(Object.entries(schema.properties ?? {}) as [string, JsonSchema][]);
  const required = $derived(new Set<string>(schema.required ?? []));

  function resolve(s: JsonSchema): JsonSchema {
    // Follow $ref: "#/$defs/X" into defs; unwrap anyOf [X, null] (Optional)
    if (typeof s === "object" && s !== null && "$ref" in s) {
      const ref = s.$ref as string;
      if (ref.startsWith("#/$defs/")) {
        const name = ref.slice("#/$defs/".length);
        return defs[name] ?? s;
      }
    }
    // Unwrap anyOf with null (Optional pattern)
    if (Array.isArray(s.anyOf)) {
      const optional = s.anyOf.find((item) => item === null || (typeof item === "object" && item !== null && "const" in item && item.const === null));
      if (optional) {
        return resolve(optional);
      }
    }
    return s;
  }

  function set(key: string, v: unknown): void {
    onchange({ ...value, [key]: v }, overridable);
  }

  function toggleOverridable(key: string, on: boolean): void {
    onchange(value, on ? [...overridable, key] : overridable.filter((k) => k !== key));
  }

  function renderWidget(
    key: string,
    propSchema: JsonSchema,
    propValue: unknown,
  ): { widget: string; props: Record<string, unknown> } {
    const resolved = resolve(propSchema);
    const isSecret = "x-secret" in resolved;
    const isServerManaged = "x-server-managed" in resolved;
    const isOverridable = "x-user-overridable" in resolved;
    const hasOptions = "x-options" in resolved && optionsLoader;
    const isOneOf = Array.isArray(resolved.oneOf);

    if (isServerManaged) {
      return { widget: "server-managed", props: { key, value: propValue } };
    }

    if (isSecret) {
      return { widget: "password", props: { key, value: propValue } };
    }

    if (isOneOf) {
      return { widget: "oneof", props: { key, value: propValue, schema: resolved, root, optionsLoader } };
    }

    const type = resolved.type as string | undefined;
    if (type === "boolean") {
      return { widget: "switch", props: { key, value: propValue } };
    }

    if (type === "integer" || type === "number") {
      return { widget: "number", props: { key, value: propValue } };
    }

    if (type === "string") {
      if (hasOptions) {
        return { widget: "multi-select", props: { key, value: propValue, optionsLoader } };
      }
      return { widget: "text", props: { key, value: propValue } };
    }

    if (type === "array") {
      const items = resolved.items as JsonSchema | undefined;
      if (items) {
        const itemsResolved = resolve(items);
        const itemsType = itemsResolved.type as string | undefined;
        if (itemsType === "string") {
          return { widget: "string-list", props: { key, value: propValue } };
        }
        if (Array.isArray(itemsResolved.oneOf)) {
          return { widget: "oneof-array", props: { key, value: propValue, schema: itemsResolved, root, optionsLoader } };
        }
      }
      return { widget: "json", props: { key, value: propValue } };
    }

    if (type === "object") {
      return { widget: "json", props: { key, value: propValue } };
    }

    return { widget: "text", props: { key, value: propValue } };
  }
</script>

{#each props as [key, propSchema]}
  <div class="flex flex-col gap-2 rounded-md border border-input bg-background p-3">
    <div class="flex items-center justify-between gap-2">
      <Label for={key} class="text-sm font-medium">
        {key}
        {#if required.has(key)}
          <span class="text-destructive">*</span>
        {/if}
      </Label>
      {#if showOverridable && isOverridable}
        <Switch
          id={`overridable-${key}`}
          checked={overridable.includes(key)}
          oncheckedchange={(e) => toggleOverridable(key, e.currentTarget.checked)}
          disabled={readonly}
        />
      {/if}
    </div>

    {#if "x-ui-help" in propSchema || "description" in propSchema}
      <AppTooltip content={(propSchema as any).x_ui_help || (propSchema as any).description || ""}>
        <span class="text-xs text-muted-foreground">Click for help</span>
      </AppTooltip>
    {/if}

    {#if readonly}
      <div class="text-sm text-muted-foreground">Read-only (wired by the server)</div>
    {:else}
      {#const widget = renderWidget(key, propSchema, value[key])}
        {#if widget.widget === "server-managed"}
          <div class="text-sm text-muted-foreground">Read-only (wired by the server)</div>
        {:else if widget.widget === "password"}
          <Input
            id={key}
            type="password"
            bind:value={value[key]}
            placeholder="••••••••"
            disabled={readonly}
            data-testid={`schema-form-password-${key}`}
          />
        {:else if widget.widget === "switch"}
          <Switch
            id={key}
            checked={value[key] as boolean}
            oncheckedchange={(e) => set(key, e.currentTarget.checked)}
            disabled={readonly}
            data-testid={`schema-form-switch-${key}`}
          />
        {:else if widget.widget === "number"}
          <Slider
            id={key}
            bind:value={value[key]}
            min={propSchema.minimum as number}
            max={propSchema.maximum as number}
            step={propSchema.multipleOf as number}
            disabled={readonly}
            data-testid={`schema-form-slider-${key}`}
          />
        {:else if widget.widget === "text"}
          <Input
            id={key}
            bind:value={value[key]}
            disabled={readonly}
            data-testid={`schema-form-text-${key}`}
          />
        {:else if widget.widget === "multi-select"}
          <Input
            id={key}
            bind:value={value[key]}
            placeholder="Type to add options..."
            disabled={readonly}
            data-testid={`schema-form-multi-select-${key}`}
          />
        {:else if widget.widget === "string-list"}
          <StringListEditor
            id={key}
            bind:items={value[key]}
            disabled={readonly}
            data-testid={`schema-form-string-list-${key}`}
          />
        {:else if widget.widget === "json"}
          <JsonEditor
            id={key}
            bind:value={value[key]}
            mode="object"
            disabled={readonly}
            data-testid={`schema-form-json-${key}`}
          />
        {:else if widget.widget === "oneof"}
          <div class="flex flex-col gap-2">
            <select
              id={`${key}-kind`}
              bind:value={value[key]}
              disabled={readonly}
              data-testid={`schema-form-oneof-kind-${key}`}
            >
              {#each (propSchema.oneOf as JsonSchema[]) as branch}
                {#if branch.const !== null}
                  <option value={branch.const}>{(branch as any).title || (branch as any).const}</option>
                {:else}
                  <option value="">Select a kind...</option>
                {/if}
              {/each}
            </select>
            {#if value[key]}
              {#each (propSchema.oneOf as JsonSchema[]) as branch}
                {#if branch.const === value[key]}
                  <SchemaForm
                    schema={branch}
                    value={value[key] as Record<string, unknown>}
                    overridable={overridable}
                    showOverridable={showOverridable}
                    optionsLoader={optionsLoader}
                    readonly={readonly}
                    onchange={set}
                    root={root}
                    data-testid={`schema-form-oneof-branch-${key}-${value[key]}`}
                  />
                {/if}
              {/each}
            {/if}
          </div>
        {:else if widget.widget === "oneof-array"}
          <div class="flex flex-col gap-2">
            <select
              id={`${key}-kind`}
              bind:value={value[key]}
              disabled={readonly}
              data-testid={`schema-form-oneof-array-kind-${key}`}
            >
              {#each (propSchema.oneOf as JsonSchema[]) as branch}
                {#if branch.const !== null}
                  <option value={branch.const}>{(branch as any).title || (branch as any).const}</option>
                {:else}
                  <option value="">Select a kind...</option>
                {/if}
              {/each}
            </select>
            {#if value[key]}
              {#each (propSchema.oneOf as JsonSchema[]) as branch}
                {#if branch.const === value[key]}
                  <SchemaForm
                    schema={branch}
                    value={value[key] as Record<string, unknown>}
                    overridable={overridable}
                    showOverridable={showOverridable}
                    optionsLoader={optionsLoader}
                    readonly={readonly}
                    onchange={set}
                    root={root}
                    data-testid={`schema-form-oneof-array-branch-${key}-${value[key]}`}
                  />
                {/if}
              {/each}
            {/if}
          </div>
        {/if}
      {/const}
    {/if}
  </div>
{/each}
