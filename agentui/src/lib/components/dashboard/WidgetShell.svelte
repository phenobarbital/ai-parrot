<script lang="ts">
	import type { Widget } from '$lib/stores/dashboard/widget.svelte';
	import type { GridConfig } from '$lib/stores/dashboard/store.svelte';
	import { createEventDispatcher } from 'svelte';

	let {
		widget,
		children,
		gridConfig,
		containerWidth,
		layoutMode = 'grid'
	} = $props<{
		widget: Widget;
		children?: import('svelte').Snippet;
		gridConfig?: GridConfig;
		containerWidth?: number;
		layoutMode?: 'grid' | 'free' | 'dock';
	}>();

	const dispatch = createEventDispatcher();

	// Interaction State
	let isDragging = $state(false);
	let isResizing = $state(false);
	let startX = 0;
	let startY = 0;
	let initialPos = { x: 0, y: 0, w: 0, h: 0 };
	let startWidth = 0;
	let startHeight = 0;

	let dragTransform = $state('');

	// --- Drag Logic ---
	function onDragStart(e: PointerEvent) {
		if (widget.maximized) return; // No drag when maximized
		if ((e.target as HTMLElement).closest('button')) return; // Ignore button clicks
		if (layoutMode === 'dock') return; // Dock dragging handled by DockLayout (tabs)

		isDragging = true;
		startX = e.clientX;
		startY = e.clientY;
		initialPos = { ...widget.position };

		window.addEventListener('pointermove', onDragMove);
		window.addEventListener('pointerup', onDragEnd);
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onDragMove(e: PointerEvent) {
		if (!isDragging) return;

		const dx = e.clientX - startX;
		const dy = e.clientY - startY;

		if (layoutMode === 'free' || widget.floating) {
			widget.position.x += dx;
			widget.position.y += dy;
			startX = e.clientX;
			startY = e.clientY;
		} else if (layoutMode === 'grid') {
			// Grid Mode: Visual Drag only
			dragTransform = `translate(${dx}px, ${dy}px)`;
		}
	}

	function onDragEnd(e: PointerEvent) {
		if (!isDragging) return;

		// Commit Grid Drop
		if (layoutMode === 'grid' && !widget.floating && gridConfig && containerWidth) {
			const totalDx = e.clientX - startX;
			const totalDy = e.clientY - startY;

			// Calculate Grid Units
			const gap = gridConfig.gap;
			const cols = gridConfig.cols;
			const colWidth = (containerWidth - gap * (cols - 1)) / cols;
			const rowHeight = gridConfig.rowHeight;

			const deltaCols = Math.round(totalDx / (colWidth + gap));
			const deltaRows = Math.round(totalDy / (rowHeight + gap));

			if (deltaCols !== 0 || deltaRows !== 0) {
				const newX = Math.max(0, initialPos.x + deltaCols);
				const newY = Math.max(0, initialPos.y + deltaRows);

				widget.position.x = newX;
				widget.position.y = newY;
			}
		}

		isDragging = false;
		dragTransform = ''; // Reset visual
		window.removeEventListener('pointermove', onDragMove);
		window.removeEventListener('pointerup', onDragEnd);
	}

	// --- Resize Logic ---
	function onResizeStart(e: PointerEvent) {
		e.stopPropagation();
		isResizing = true;
		startX = e.clientX;
		startY = e.clientY;
		startWidth = widget.position.w;
		startHeight = widget.position.h;

		window.addEventListener('pointermove', onResizeMove);
		window.addEventListener('pointerup', onResizeEnd);
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onResizeMove(e: PointerEvent) {
		if (!isResizing) return;

		const dx = e.clientX - startX;
		const dy = e.clientY - startY;

		if (layoutMode === 'free' || widget.floating) {
			widget.position.w = Math.max(100, startWidth + dx);
			widget.position.h = Math.max(100, startHeight + dy);
		} else if (layoutMode === 'grid') {
			// Grid resize logic could be implemented here
		}
	}

	function onResizeEnd() {
		isResizing = false;
		window.removeEventListener('pointermove', onResizeMove);
		window.removeEventListener('pointerup', onResizeEnd);
	}

	// Derived styles for positioning based on state
	let style = $derived.by(() => {
		// Maximized: Fixed Fullscreen
		if (widget.maximized) {
			return `
                position: fixed;
                top: 0; left: 0; right: 0; bottom: 0;
                z-index: 9999; /* Ensure high z-index */
                margin: 0;
            `;
		}

		// Floating: Absolute positioning
		if (widget.floating || layoutMode === 'free') {
			return `
                position: absolute;
                left: ${widget.position.x}px;
                top: ${widget.position.y}px;
                width: ${widget.position.w}px;
                height: ${widget.position.h}px;
                z-index: ${widget.zIndex + (isDragging ? 100 : 0)};
                transition: ${isDragging ? 'none' : 'all 0.1s'};
            `;
		}

		// Dock Mode: Height/Width controlled by flex container usually, but basic styles here
		if (layoutMode === 'dock') {
			return `
                width: 100%;
                height: 100%;
                overflow: hidden;
            `;
		}

		// Default: Grid Flow (if parent is grid)
		return `
            grid-column: span ${widget.position.w};
            grid-row: span ${widget.minimized ? 1 : widget.position.h};
            z-index: ${isDragging ? 100 : widget.zIndex};
            ${dragTransform ? `transform: ${dragTransform}; pointer-events: none; opacity: 0.8;` : ''}
            transition: ${isDragging ? 'none' : 'all 0.2s'};
        `;
	});

	let contentClass = $derived(
		widget.minimized ? 'hidden' : 'flex-1 overflow-auto min-h-0 relative'
	);
</script>

<div
	class="card bg-base-100 border-base-300 flex flex-col border shadow-xl transition-all duration-200"
	class:h-full={!widget.minimized && !widget.maximized}
	{style}
>
	<!-- Header -->
	<div
		class="border-base-200 handle bg-base-200/30 flex cursor-grab select-none items-center justify-between border-b px-3 py-2 active:cursor-grabbing"
		role="button"
		tabindex="0"
		onpointerdown={onDragStart}
		ondblclick={() => widget.toggleMaximize()}
	>
		<div class="flex items-center gap-2 truncate text-sm font-medium">
			<span>{widget.title}</span>
			{#if widget.isLoading}
				<span class="loading loading-spinner loading-xs text-primary"></span>
			{/if}
		</div>

		<!-- Window Controls -->
		<div class="flex shrink-0 items-center gap-1">
			<!-- Float Toggle -->
			<button
				class="btn btn-ghost btn-xs btn-square opacity-70 hover:opacity-100"
				title={widget.floating ? 'Dock' : 'Float'}
				onclick={() => widget.setFloating(!widget.floating)}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="h-3.5 w-3.5"
				>
					{#if widget.floating}
						<path
							d="M5.25 3A2.25 2.25 0 0 0 3 5.25v9.5A2.25 2.25 0 0 0 5.25 17h9.5A2.25 2.25 0 0 0 17 14.75v-9.5A2.25 2.25 0 0 0 14.75 3h-9.5Zm.75 4h8a.75.75 0 0 1 0 1.5H6a.75.75 0 0 1 0-1.5Z"
						/>
					{:else}
						<path
							fill-rule="evenodd"
							d="M2.25 5.5a.75.75 0 0 1 .75-.75h14a.75.75 0 0 1 0 1.5H3a.75.75 0 0 1-.75-.75Zm0 4a.75.75 0 0 1 .75-.75h14a.75.75 0 0 1 0 1.5H3a.75.75 0 0 1-.75-.75Zm0 4a.75.75 0 0 1 .75-.75h14a.75.75 0 0 1 0 1.5H3a.75.75 0 0 1-.75-.75Z"
							clip-rule="evenodd"
						/>
					{/if}
				</svg>
			</button>

			<!-- Minimize -->
			<button
				class="btn btn-ghost btn-xs btn-square opacity-70 hover:opacity-100"
				title={widget.minimized ? 'Expand' : 'Minimize'}
				onclick={() => widget.toggleMinimize()}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="h-4 w-4"
				>
					<path
						fill-rule="evenodd"
						d="M4 10a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H4.75A.75.75 0 014 10z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>

			<!-- Maximize/Restore -->
			<button
				class="btn btn-ghost btn-xs btn-square opacity-70 hover:opacity-100"
				title={widget.maximized ? 'Restore' : 'Maximize'}
				onclick={() => widget.toggleMaximize()}
			>
				{#if widget.maximized}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="h-3.5 w-3.5"
					>
						<path
							d="M5.25 3A2.25 2.25 0 003 5.25v9.5A2.25 2.25 0 005.25 17h9.5A2.25 2.25 0 0017 14.75v-9.5A2.25 2.25 0 0014.75 3h-9.5zm0 1.5h9.5a.75.75 0 01.75.75v9.5a.75.75 0 01-.75.75h-9.5a.75.75 0 01-.75-.75v-9.5a.75.75 0 01.75-.75z"
						/>
					</svg>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="h-3.5 w-3.5"
					>
						<path
							fill-rule="evenodd"
							d="M4.25 2A2.25 2.25 0 002 4.25v11.5A2.25 2.25 0 004.25 18h11.5A2.25 2.25 0 0018 15.75V4.25A2.25 2.25 0 0015.75 2H4.25zm0 1.5h11.5a.75.75 0 01.75.75v11.5a.75.75 0 01-.75.75H4.25a.75.75 0 01-.75-.75V4.25a.75.75 0 01.75-.75z"
							clip-rule="evenodd"
						/>
					</svg>
				{/if}
			</button>

			<!-- Menu (Placeholder for Settings) -->
			<button
				class="btn btn-ghost btn-xs btn-square opacity-70 hover:opacity-100"
				aria-label="Menu"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="h-4 w-4"
				>
					<path
						fill-rule="evenodd"
						d="M2 10a.75.75 0 01.75-.75h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 10z"
						clip-rule="evenodd"
					/>
					<path
						d="M2.75 6a.75.75 0 000 1.5h14.5a.75.75 0 000-1.5H2.75zM2.75 13a.75.75 0 000 1.5h14.5a.75.75 0 000-1.5H2.75z"
					/>
				</svg>
			</button>

			<!-- Close -->
			<button
				class="btn btn-ghost btn-xs btn-square text-error/70 hover:text-error hover:bg-error/10"
				aria-label="Close"
				onclick={() => dispatch('close', widget.id)}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="h-4 w-4"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>
	</div>

	<!-- Content -->
	<div class={contentClass}>
		{@render children?.()}
	</div>

	<!-- Resize Handle (Bottom Right) -->
	{#if !widget.minimized && !widget.maximized}
		<div
			class="absolute bottom-0 right-0 z-50 h-4 w-4 cursor-nwse-resize opacity-0 hover:opacity-100"
			role="button"
			tabindex="0"
			onpointerdown={onResizeStart}
		>
			<svg viewBox="0 0 24 24" class="fill-base-content/50 h-full w-full">
				<path d="M22 22v-20h-2v20h-20v2h22z" />
			</svg>
		</div>
	{/if}
</div>
