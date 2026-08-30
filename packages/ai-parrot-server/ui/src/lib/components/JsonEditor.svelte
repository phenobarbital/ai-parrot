<!--
  JsonEditor (TASK-2585, FEAT-475) — validated JSON textarea for the agent
  form's JSONB fields (model_config, prompt_config, vector_store_config,
  reranker_config, parent_searcher_config, memory_config, permissions).

  Resolved design (spec §8 Q1): a zero-dependency validated textarea, not
  an external JSON editor library (svelte-jsoneditor et al. are NOT
  dependencies of this feature).

  `value` is bindable and only updated when the current textarea contents
  parse as valid JSON of the expected `mode` — invalid input shows an
  inline error but never clobbers the last known-valid `value`, so a
  consumer bound to `value` (e.g. AgentFormState) never observes a
  malformed payload. `valid` mirrors that state for callers that want to
  gate Save without inspecting the error text themselves.

  Note: `value` is read once at mount to seed the textarea; a later
  external reassignment (e.g. loading an existing agent asynchronously
  after this component has already mounted) will not resync the textarea
  on its own — wrap the consumer in a `{#key ...}` block (or otherwise
  remount) when swapping in freshly-loaded data, the standard Svelte
  pattern for this class of "seed once" widget.
-->
<script lang="ts">
	import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
	import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
	import { Textarea } from "$lib/ui/internal/shadcn/ui/textarea/index.js";
	import { cn } from "$lib/ui/internal/shadcn/utils.js";

	type Mode = "object" | "array" | "any";

	let {
		value = $bindable(),
		mode = "any",
		label,
		hint,
		valid = $bindable(true),
		onvalid,
		id,
		class: className,
	}: {
		value?: unknown;
		mode?: Mode;
		label?: string;
		hint?: string;
		valid?: boolean;
		onvalid?: (valid: boolean) => void;
		id?: string;
		class?: string;
	} = $props();

	function seedDefault(): unknown {
		if (value !== undefined) return value;
		return mode === "array" ? [] : {};
	}

	let text = $state(JSON.stringify(seedDefault(), null, 2));
	let error = $state<string | null>(null);

	function shapeError(parsed: unknown): string | null {
		if (mode === "object") {
			if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
				return "Value must be a JSON object";
			}
		} else if (mode === "array") {
			if (!Array.isArray(parsed)) {
				return "Value must be a JSON array";
			}
		}
		return null;
	}

	function validate(): void {
		try {
			const parsed = JSON.parse(text);
			const shapeErr = shapeError(parsed);
			if (shapeErr) {
				error = shapeErr;
				valid = false;
			} else {
				error = null;
				valid = true;
				value = parsed;
			}
		} catch (err) {
			error = err instanceof Error ? err.message : "Invalid JSON";
			valid = false;
		}
		onvalid?.(valid);
	}

	function format(): void {
		try {
			const parsed = JSON.parse(text);
			text = JSON.stringify(parsed, null, 2);
		} catch {
			// Malformed JSON — nothing to pretty-print; leave text as-is,
			// the inline error already reflects the problem.
		}
		validate();
	}

	// Validate once at creation so `valid`/`error` reflect the seeded value
	// immediately, without waiting for the first keystroke.
	validate();
</script>

<div class={cn("flex flex-col gap-1.5", className)} data-testid="json-editor">
	<div class="flex items-center justify-between gap-2">
		{#if label}
			<Label for={id}>{label}</Label>
		{:else}
			<span></span>
		{/if}
		<Button
			type="button"
			variant="ghost"
			size="sm"
			onclick={format}
			data-testid="json-editor-format"
		>
			Format
		</Button>
	</div>
	<Textarea
		{id}
		bind:value={text}
		oninput={validate}
		rows={8}
		class="font-mono text-xs"
		aria-invalid={error ? "true" : undefined}
		data-testid="json-editor-textarea"
	/>
	{#if error}
		<p class="text-destructive text-xs" data-testid="json-editor-error">{error}</p>
	{:else if hint}
		<p class="text-muted-foreground text-xs">{hint}</p>
	{/if}
</div>
