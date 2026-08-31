<script lang="ts">
	import { Slider as SliderPrimitive } from "bits-ui";
	import {
		cn,
		type WithElementRef,
		type WithoutChildrenOrChild,
	} from "$lib/ui/internal/shadcn/utils.js";

	let {
		ref = $bindable(null),
		value = $bindable(0),
		type = "single",
		orientation = "horizontal",
		class: className,
		...restProps
	}: WithoutChildrenOrChild<WithElementRef<SliderPrimitive.RootProps>> =
		$props();
</script>

<SliderPrimitive.Root
	bind:ref
	bind:value
	{type}
	{orientation}
	data-slot="slider"
	class={cn(
		"relative flex w-full touch-none items-center select-none data-[disabled]:opacity-50 data-[orientation=vertical]:h-full data-[orientation=vertical]:min-h-44 data-[orientation=vertical]:w-auto data-[orientation=vertical]:flex-col",
		className,
	)}
	{...restProps}
>
	{#snippet children({ thumbItems })}
		<span
			data-slot="slider-track"
			class="bg-muted relative grow overflow-hidden rounded-full data-[orientation=horizontal]:h-1.5 data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-1.5"
			data-orientation={orientation}
		>
			<SliderPrimitive.Range
				data-slot="slider-range"
				class="bg-primary absolute data-[orientation=horizontal]:h-full data-[orientation=vertical]:w-full"
			/>
		</span>
		{#each thumbItems as thumb (thumb.index)}
			<SliderPrimitive.Thumb
				index={thumb.index}
				data-slot="slider-thumb"
				class="border-primary bg-background ring-ring/50 block size-4 shrink-0 rounded-full border shadow-sm transition-[color,box-shadow] hover:ring-4 focus-visible:ring-4 focus-visible:outline-hidden disabled:pointer-events-none disabled:opacity-50"
			/>
		{/each}
	{/snippet}
</SliderPrimitive.Root>
