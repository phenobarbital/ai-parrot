<script lang="ts">
	import { Switch as SwitchPrimitive } from "bits-ui";
	import {
		cn,
		type WithElementRef,
		type WithoutChildrenOrChild,
	} from "$lib/ui/internal/shadcn/utils.js";

	let {
		ref = $bindable(null),
		checked = $bindable(false),
		class: className,
		...restProps
	}: WithoutChildrenOrChild<WithElementRef<SwitchPrimitive.RootProps>> =
		$props();
</script>

<SwitchPrimitive.Root
	bind:ref
	bind:checked
	data-slot="switch"
	class={cn(
		"peer data-[state=checked]:bg-primary data-[state=unchecked]:bg-input focus-visible:border-ring focus-visible:ring-ring/50 inline-flex h-[1.15rem] w-8 shrink-0 items-center rounded-full border border-transparent shadow-xs transition-all outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50",
		className,
	)}
	{...restProps}
>
	<SwitchPrimitive.Thumb
		data-slot="switch-thumb"
		class={cn(
			"bg-background pointer-events-none block size-4 rounded-full ring-0 transition-transform data-[state=checked]:translate-x-[calc(100%-2px)] data-[state=unchecked]:translate-x-0",
		)}
	/>
</SwitchPrimitive.Root>
