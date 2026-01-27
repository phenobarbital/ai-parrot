<script lang="ts">
	import { workspace } from '$lib/stores/dashboard/workspace.svelte';
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	// Menu state
	let activeMenuId = $state<string | null>(null);
	let menuPosition = $state({ x: 0, y: 0 });

	let activeMenuDash = $derived(
		activeMenuId ? workspace.dashboards.find((d) => d.id === activeMenuId) : null
	);

	function handleContextMenu(e: MouseEvent, id: string) {
		e.preventDefault();
		e.stopPropagation();

		if (activeMenuId === id) {
			closeMenu();
			return;
		}

		const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
		// Position below the button, aligned left, but check for overflow in a real app (simplified here)
		menuPosition = {
			x: rect.left,
			y: rect.bottom + 5
		};
		activeMenuId = id;
	}

	function closeMenu() {
		activeMenuId = null;
	}

	// Close menu on outside click
	function onWindowClick(e: Event) {
		if (!activeMenuId) return;
		const target = e.target as HTMLElement;
		// Check if click is inside the menu or on a dashboard action button
		if (!target.closest('.dashboard-menu') && !target.closest('.dashboard-action-btn')) {
			closeMenu();
		}
	}
</script>

<svelte:window onclick={onWindowClick} />

<div class="bg-base-200 flex items-center gap-1 border-b px-2 py-1">
	<div class="no-scrollbar flex flex-1 items-center gap-1 overflow-x-auto">
		{#each workspace.dashboards as dash (dash.id)}
			<!-- Changed to div with role=button to allow nesting interactive elements -->
			<div
				class="btn btn-sm join-item group relative cursor-pointer flex-nowrap gap-2 font-normal normal-case transition-all"
				class:btn-active={workspace.activeDashboardId === dash.id}
				class:btn-ghost={workspace.activeDashboardId !== dash.id}
				class:bg-base-100={workspace.activeDashboardId === dash.id}
				class:shadow-sm={workspace.activeDashboardId === dash.id}
				role="button"
				tabindex="0"
				onclick={(e) => {
					// Prevent activation if clicking menu/close buttons
					if ((e.target as HTMLElement).closest('.dashboard-action-btn')) return;
					workspace.activate(dash.id);
				}}
				onkeydown={(e) => {
					if (e.key === 'Enter' || e.key === ' ') {
						if ((e.target as HTMLElement).closest('.dashboard-action-btn')) return;
						workspace.activate(dash.id);
					}
				}}
			>
				<span>{dash.icon}</span>
				<span>{dash.title}</span>
				<span class="text-xs opacity-50">
					({dash.layoutMode})
				</span>

				<!-- 3-dot menu trigger -->
				<button
					class="btn btn-xs btn-ghost btn-circle dashboard-action-btn relative z-10 h-5 min-h-0 w-5"
					onclick={(e) => handleContextMenu(e, dash.id)}
				>
					⋮
				</button>

				<button
					class="btn btn-xs btn-ghost btn-circle hover:bg-base-300 dashboard-action-btn relative z-10 h-4 min-h-0 w-4 opacity-0 group-hover:opacity-100"
					onclick={(e) => {
						e.stopPropagation();
						workspace.removeDashboard(dash.id);
					}}
				>
					×
				</button>
			</div>
		{/each}
	</div>

	<button
		class="btn btn-sm btn-ghost btn-square"
		onclick={() => workspace.addDashboard('New Dashboard')}
		title="Add Dashboard"
	>
		+
	</button>
</div>

<!-- Global Menu using Fixed Positioning -->
{#if activeMenuDash}
	<div
		class="dashboard-menu bg-base-100 fixed z-[9999] w-48 rounded-lg border p-1 text-left shadow-lg"
		style="top: {menuPosition.y}px; left: {menuPosition.x}px;"
	>
		<button
			class="btn btn-ghost btn-xs w-full content-center justify-start"
			onclick={() => {
				dispatch('rename', activeMenuDash);
				closeMenu();
			}}
		>
			✏️ Rename
		</button>
		<button
			class="btn btn-ghost btn-xs w-full content-center justify-start"
			onclick={() => {
				dispatch('addWidget', activeMenuDash);
				closeMenu();
			}}
		>
			➕ Add Widget
		</button>
		<button
			class="btn btn-ghost btn-xs w-full content-center justify-start"
			onclick={() => {
				dispatch('settings', activeMenuDash);
				closeMenu();
			}}
		>
			⚙️ Settings
		</button>
		<div class="divider my-0"></div>
		<div class="text-base-content/50 px-2 py-1 text-xs font-bold">Layout Mode</div>
		{#each ['grid', 'free', 'dock'] as mode}
			<button
				class="btn btn-ghost btn-xs w-full justify-start capitalize"
				class:bg-base-200={activeMenuDash.layoutMode === mode}
				onclick={() => {
					activeMenuDash?.switchLayout(mode as any);
					// Keep open or close? Let's keep open for now or close?
					// User logic might want to switch and see result. Let's keep it consistent.
				}}
			>
				{activeMenuDash.layoutMode === mode ? '✓ ' : '  '}
				{mode}
			</button>
		{/each}
		<div class="divider my-0"></div>
		<button
			class="btn btn-ghost btn-xs text-error w-full justify-start"
			onclick={() => {
				if (activeMenuDash) workspace.removeDashboard(activeMenuDash.id);
				closeMenu();
			}}
		>
			🗑️ Delete
		</button>
	</div>
{/if}

<style>
	.no-scrollbar::-webkit-scrollbar {
		display: none;
	}
	.no-scrollbar {
		-ms-overflow-style: none;
		scrollbar-width: none;
	}
</style>
