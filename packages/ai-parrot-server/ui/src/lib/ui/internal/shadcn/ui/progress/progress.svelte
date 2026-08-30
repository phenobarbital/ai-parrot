<script lang="ts">
	import { Progress as ProgressPrimitive } from "bits-ui";
	import {
		cn,
		type WithoutChildrenOrChild,
	} from "$lib/ui/internal/shadcn/utils.js";

	let {
		ref = $bindable(null),
		class: className,
		max = 100,
		value,
		...restProps
	}: WithoutChildrenOrChild<ProgressPrimitive.RootProps> = $props();

	const pct = $derived.by(() => {
		const safeMax = Math.max(max ?? 100, 1);
		const clamped = Math.min(Math.max(value ?? 0, 0), safeMax);
		return 100 - (100 * clamped) / safeMax;
	});
</script>

<ProgressPrimitive.Root
	bind:ref
	data-slot="progress"
	class={cn(
		"bg-primary/20 relative h-2 w-full overflow-hidden rounded-full",
		className,
	)}
	{value}
	{max}
	{...restProps}
>
	<div
		data-slot="progress-indicator"
		class="bg-primary h-full w-full flex-1 transition-all"
		style="transform: translateX(-{pct}%)"
	></div>
</ProgressPrimitive.Root>
