<!--
  StringListEditor (TASK-2585, FEAT-475) — add/remove/reorder editor for
  `string[]` fields on the agent form: `pre_instructions`, `tools`,
  `custom_kbs`. `tools`/`custom_kbs` pass `suggestions` (a datalist) sourced
  from GET /api/v1/agent_tools / GET /api/v1/admin/catalog — wired by the
  form (TASK-2587/2586), not this widget.
-->
<script lang="ts">
	import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
	import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
	import { cn } from "$lib/ui/internal/shadcn/utils.js";

	let {
		items = $bindable([]),
		suggestions,
		placeholder = "Add an item…",
		id,
		class: className,
	}: {
		items?: string[];
		suggestions?: string[];
		placeholder?: string;
		id?: string;
		class?: string;
	} = $props();

	let draft = $state("");
	let datalistId = $derived(id ? `${id}-suggestions` : undefined);

	function addDraft(): void {
		const trimmed = draft.trim();
		if (!trimmed) return;
		items = [...items, trimmed];
		draft = "";
	}

	function remove(index: number): void {
		items = items.filter((_, i) => i !== index);
	}

	function moveUp(index: number): void {
		if (index <= 0) return;
		const next = [...items];
		[next[index - 1], next[index]] = [next[index], next[index - 1]];
		items = next;
	}

	function moveDown(index: number): void {
		if (index >= items.length - 1) return;
		const next = [...items];
		[next[index], next[index + 1]] = [next[index + 1], next[index]];
		items = next;
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === "Enter") {
			event.preventDefault();
			addDraft();
		}
	}
</script>

<div class={cn("flex flex-col gap-2", className)} data-testid="string-list-editor">
	<div class="flex gap-2">
		<Input
			{id}
			bind:value={draft}
			{placeholder}
			list={datalistId}
			onkeydown={handleKeydown}
			data-testid="string-list-editor-input"
		/>
		<Button type="button" variant="outline" onclick={addDraft} data-testid="string-list-editor-add">
			Add
		</Button>
	</div>
	{#if suggestions && suggestions.length > 0 && datalistId}
		<datalist id={datalistId} data-testid="string-list-editor-suggestions">
			{#each suggestions as suggestion (suggestion)}
				<option value={suggestion}></option>
			{/each}
		</datalist>
	{/if}
	{#if items.length > 0}
		<ul class="flex flex-col gap-1" data-testid="string-list-editor-items">
			{#each items as item, index (index)}
				<li class="border-input flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
					<span class="flex-1 truncate">{item}</span>
					<Button
						type="button"
						variant="ghost"
						size="icon-sm"
						disabled={index === 0}
						onclick={() => moveUp(index)}
						data-testid="string-list-editor-up-{index}"
						aria-label="Move {item} up"
					>
						↑
					</Button>
					<Button
						type="button"
						variant="ghost"
						size="icon-sm"
						disabled={index === items.length - 1}
						onclick={() => moveDown(index)}
						data-testid="string-list-editor-down-{index}"
						aria-label="Move {item} down"
					>
						↓
					</Button>
					<Button
						type="button"
						variant="ghost"
						size="icon-sm"
						onclick={() => remove(index)}
						data-testid="string-list-editor-remove-{index}"
						aria-label="Remove {item}"
					>
						×
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</div>
