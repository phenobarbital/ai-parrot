<script lang="ts">
	import { Checkbox as CheckboxPrimitive } from "bits-ui";
	import {
		cn,
		type WithElementRef,
		type WithoutChildrenOrChild,
	} from "$lib/ui/internal/shadcn/utils.js";

	let {
		ref = $bindable(null),
		checked = $bindable(false),
		indeterminate = $bindable(false),
		class: className,
		...restProps
	}: WithoutChildrenOrChild<
		WithElementRef<CheckboxPrimitive.RootProps>
	> = $props();
</script>

<CheckboxPrimitive.Root
	bind:ref
	bind:checked
	bind:indeterminate
	data-slot="checkbox"
	class={cn(
		"peer border-input dark:bg-input/30 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground data-[state=checked]:border-primary focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive size-4 shrink-0 rounded-[4px] border shadow-xs transition-shadow outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50",
		className,
	)}
	{...restProps}
>
	{#snippet children({ checked: isChecked, indeterminate: isIndeterminate })}
		<div
			data-slot="checkbox-indicator"
			class="flex items-center justify-center text-current transition-none"
		>
			{#if isIndeterminate}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="3"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-3.5"
				>
					<path d="M5 12h14" />
				</svg>
			{:else if isChecked}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="3"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-3.5"
				>
					<path d="M20 6 9 17l-5-5" />
				</svg>
			{/if}
		</div>
	{/snippet}
</CheckboxPrimitive.Root>
