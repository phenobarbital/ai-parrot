<script lang="ts">
	import { Switch } from 'bits-ui';

	let {
		checked = $bindable(false),
		disabled = false,
		label,
		ariaLabel,
		onCheckedChange,
		size = 'md'
	}: {
		checked: boolean;
		disabled?: boolean;
		/** Visible label rendered next to the switch. */
		label?: string;
		/** Accessible name when there is no visible label (e.g. the label lives
		 *  in surrounding markup). Ignored when `label` is provided. */
		ariaLabel?: string;
		/** Fires with the new checked state — for callback-style consumers that
		 *  don't bind `checked` (e.g. schema-driven forms). */
		onCheckedChange?: (checked: boolean) => void;
		/** `sm` matches compact form controls (input-sm/select-sm ~30px row). */
		size?: 'sm' | 'md';
	} = $props();

	let root = $derived(size === 'sm' ? 'h-5 w-9' : 'h-6 w-11');
	let thumb = $derived(
		size === 'sm'
			? 'h-3.5 w-3.5 data-[state=checked]:translate-x-4'
			: 'h-5 w-5 data-[state=checked]:translate-x-5'
	);
	let labelText = $derived(size === 'sm' ? 'text-xs' : 'text-sm');
</script>

<div class="inline-flex items-center gap-2">
	<Switch.Root
		bind:checked
		{disabled}
		{onCheckedChange}
		aria-label={label ?? ariaLabel}
		class="relative inline-flex {root} shrink-0 cursor-pointer rounded-full border-2 border-transparent bg-gray-300 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 data-[state=checked]:bg-primary-600 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50 dark:bg-gray-600 dark:focus:ring-offset-gray-800 dark:data-[state=checked]:bg-primary-500"
	>
		<Switch.Thumb
			class="pointer-events-none inline-block {thumb} rounded-full bg-white shadow-sm ring-0 transition-transform duration-200 data-[state=unchecked]:translate-x-0"
		/>
	</Switch.Root>
	{#if label}
		<span class="{labelText} text-base-content" class:opacity-50={disabled}>{label}</span>
	{/if}
</div>
