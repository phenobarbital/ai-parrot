<script lang="ts">
	import { Dialog } from "bits-ui";
	import type { Snippet } from "svelte";

	let {
		open = $bindable(false),
		title,
		eyebrow,
		size = "md",
		dismissible = true,
		bodyHeight,
		onclose,
		children,
		footer,
	}: {
		open: boolean;
		title?: string;
		eyebrow?: string;
		size?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl";
		dismissible?: boolean;
		/** When set, locks the body to this CSS height (e.g. "600px") so the
		 *  dialog total height stays constant regardless of inner content. The
		 *  body keeps its own overflow-y-auto so long content scrolls inside. */
		bodyHeight?: string;
		onclose?: () => void;
		children: Snippet;
		footer?: Snippet;
	} = $props();

	const sizeClasses: Record<string, string> = {
		sm: "max-w-sm",
		md: "max-w-md",
		lg: "max-w-lg",
		xl: "max-w-xl",
		"2xl": "max-w-2xl",
		"3xl": "max-w-3xl",
	};

	function handleOpenChange(value: boolean) {
		open = value;
		if (!value && onclose) {
			onclose();
		}
	}
</script>

<Dialog.Root bind:open onOpenChange={handleOpenChange}>
	<Dialog.Portal>
		<Dialog.Overlay
			class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity duration-200"
		/>
		<Dialog.Content
			class="fixed left-1/2 top-1/2 z-50 w-full -translate-x-1/2 -translate-y-1/2 rounded-lg border border-base-200 bg-base-100 shadow-xl transition-all duration-200 flex flex-col max-h-[90vh] {sizeClasses[
				size
			]}"
			onEscapeKeydown={dismissible
				? undefined
				: (e) => e.preventDefault()}
			onInteractOutside={dismissible
				? undefined
				: (e) => e.preventDefault()}
		>
			{#if title || eyebrow}
				<Dialog.Title
					class="flex-shrink-0 px-6 pt-5 pb-4 border-b border-base-200"
				>
					{#if eyebrow}
						<span class="block text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80 mb-1">
							{eyebrow}
						</span>
					{/if}
					{#if title}
						<span class="block text-lg font-semibold text-base-content leading-tight">
							{title}
						</span>
					{/if}
				</Dialog.Title>
			{/if}

			<div
				class="text-base-content overflow-y-auto px-6 py-4 {bodyHeight ? '' : 'flex-1'}"
				style={bodyHeight ? `height: ${bodyHeight}` : undefined}
			>
				{@render children()}
			</div>

			{#if footer}
				<div class="flex-shrink-0 px-6 pb-4 pt-3 border-t border-base-200 flex justify-end gap-2">
					{@render footer()}
				</div>
			{/if}

			{#if dismissible}
				<Dialog.Close
					class="absolute right-3 top-3 rounded-md p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
				>
					<svg
						class="h-5 w-5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M6 18L18 6M6 6l12 12"
						/>
					</svg>
				</Dialog.Close>
			{/if}
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>
