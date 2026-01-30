<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth';
	import { clientStore } from '$lib/stores/client.svelte';
	import { toolbarStore } from '$lib/stores/toolbar.svelte';
	import { notificationStore } from '$lib/stores/notifications.svelte';
	import { AuthGuard } from '$lib/navauth';
	import { ThemeSwitcher } from '../../../components';
	import ToastContainer from '$lib/components/common/ToastContainer.svelte';
	import type { Program, Module, Submodule } from '$lib/types';

	// Get data from page
	const program = $derived($page.data.program as Program);
	const modules = $derived(($page.data.modules as Module[]) || []);
	const client = $derived($page.data.client);
	const clientName = $derived(client?.name || 'AI Parrot');

	// User info from auth
	let user = $state<{
		displayName: string;
		email: string;
		firstName: string;
		lastName: string;
		avatar?: string;
	} | null>(null);

	$effect(() => {
		const unsubscribe = auth.subscribe((state) => {
			if (state.user) {
				user = {
					displayName: state.user.displayName,
					email: state.user.email,
					firstName: state.user.firstName || state.user.displayName?.split(' ')[0] || 'U',
					lastName: state.user.lastName || '',
					avatar: state.user.avatar
				};
			}
		});
		return unsubscribe;
	});

	// Sidebar state
	let sidebarCollapsed = $state(false);
	let expandedModules = $state<Set<string>>(new Set());

	// Current route params
	const currentModule = $derived($page.params.module);
	const currentSubmodule = $derived($page.params.submodule);

	// Generic user icon path
	const userIconPath =
		'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z';

	function toggleModule(moduleId: string) {
		if (expandedModules.has(moduleId)) {
			expandedModules.delete(moduleId);
		} else {
			expandedModules.add(moduleId);
		}
		expandedModules = new Set(expandedModules);
	}

	function isModuleActive(module: Module): boolean {
		return currentModule === module.slug;
	}

	function isSubmoduleActive(submodule: Submodule): boolean {
		return currentSubmodule === submodule.slug;
	}

	function navigateToSubmodule(module: Module, submodule: Submodule) {
		goto(`/program/${program.slug}/${module.slug}/${submodule.slug}`);
	}

	function navigateToModule(module: Module) {
		if (module.submodules.length > 0) {
			toggleModule(module.id);
		}
	}

	async function handleLogout() {
		auth.logout();
		goto('/login');
	}

	function goToPrograms() {
		goto('/programs');
	}

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
	}

	function handleMarkAllRead() {
		notificationStore.markAllAsRead();
	}

	function handleNotificationClick(id: string) {
		notificationStore.markAsRead(id);
	}

	// Get user initials for avatar
	const userInitials = $derived(() => {
		if (!user) return 'U';
		const first = user.firstName?.charAt(0) || '';
		const last = user.lastName?.charAt(0) || '';
		return (first + last).toUpperCase() || 'U';
	});

	function getIconPath(icon?: string): string {
		const iconMap: Record<string, string> = {
			'mdi:cart':
				'M7 18c-1.1 0-1.99.9-1.99 2S5.9 22 7 22s2-.9 2-2-.9-2-2-2zM1 2v2h2l3.6 7.59-1.35 2.45c-.16.28-.25.61-.25.96 0 1.1.9 2 2 2h12v-2H7.42c-.14 0-.25-.11-.25-.25l.03-.12.9-1.63h7.45c.75 0 1.41-.41 1.75-1.03l3.58-6.49c.08-.14.12-.31.12-.48 0-.55-.45-1-1-1H5.21l-.94-2H1zm16 16c-1.1 0-1.99.9-1.99 2s.89 2 1.99 2 2-.9 2-2-.9-2-2-2z',
			'mdi:package-variant-closed':
				'M21 16.5c0 .38-.21.71-.53.88l-7.9 4.44c-.16.12-.36.18-.57.18-.21 0-.41-.06-.57-.18l-7.9-4.44A.991.991 0 0 1 3 16.5v-9c0-.38.21-.71.53-.88l7.9-4.44c.16-.12.36-.18.57-.18.21 0 .41.06.57.18l7.9 4.44c.32.17.53.5.53.88v9z',
			'mdi:chart-areaspline':
				'M17.45 15.18L22 7.31V19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h1v12.87l4.05-4.87 3.27 2.18 5.13-7.85',
			'mdi:account-group':
				'M12 5.5A3.5 3.5 0 0 1 15.5 9a3.5 3.5 0 0 1-3.5 3.5A3.5 3.5 0 0 1 8.5 9 3.5 3.5 0 0 1 12 5.5M5 8c.56 0 1.08.15 1.53.42-.15 1.43.27 2.85 1.13 3.96C7.16 13.34 6.16 14 5 14a3 3 0 0 1-3-3 3 3 0 0 1 3-3m14 0a3 3 0 0 1 3 3 3 3 0 0 1-3 3c-1.16 0-2.16-.66-2.66-1.62a5.536 5.536 0 0 0 1.13-3.96c.45-.27.97-.42 1.53-.42M5.5 18.25c0-2.07 2.91-3.75 6.5-3.75s6.5 1.68 6.5 3.75V20h-13v-1.75M0 20v-1.5c0-1.39 1.89-2.56 4.45-2.9-.59.68-.95 1.62-.95 2.65V20H0m24 0h-3.5v-1.75c0-1.03-.36-1.97-.95-2.65 2.56.34 4.45 1.51 4.45 2.9V20z',
			'mdi:clock-check':
				'M16.5 10.5L15 9l-4 4-2-2-1.5 1.5L11 16l5.5-5.5M12 20a8 8 0 0 1-8-8 8 8 0 0 1 8-8 8 8 0 0 1 8 8 8 8 0 0 1-8 8m0-18A10 10 0 0 0 2 12a10 10 0 0 0 10 10 10 10 0 0 0 10-10A10 10 0 0 0 12 2z',
			'mdi:cash-register':
				'M2 17h20v2H2v-2m1-7v-2h1V4h16v4h1v2h-6v1h5v1h-5v1h5v1h-5v1h6v5H4v-5h6v-1H5v-1h5v-1H5v-1h5V9H4m5-3h6v2H9V6z',
			'mdi:clipboard-list':
				'M19 3h-4.18C14.4 1.84 13.3 1 12 1s-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2m-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1M7 7h10v2H7V7m0 4h10v2H7v-2m0 4h7v2H7v-2z',
			'mdi:keyboard-return': 'M19 7v4H5.83l3.58-3.59L8 6l-6 6 6 6 1.41-1.41L5.83 13H21V7h-2z',
			'mdi:package-variant':
				'M2 10.96a.985.985 0 0 1-.37-.07.96.96 0 0 1-.56-1.24L2.82 5.5l6.03-2.84a1 1 0 0 1 .89.01l5.26 2.69 5.26-2.69a1 1 0 0 1 .89-.01l1.76.83c.41.19.67.6.67 1.07v11.39c0 .38-.21.71-.53.88l-7.9 4.44a1.08 1.08 0 0 1-.57.18c-.21 0-.41-.06-.57-.18l-7.9-4.46A.991.991 0 0 1 5 15.93V8.64L2.64 10.7a.99.99 0 0 1-.64.26z',
			'mdi:warehouse':
				'M6 19H4V9.21l-2.91 2.18-.98-1.31L12 1l11.89 9.08-.98 1.31L20 9.21V19h-2v-8H6v8m2-6h8v2H8v-2m0 4h8v2H8v-2z',
			'mdi:truck-delivery':
				'M3 4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h1a3 3 0 0 0 6 0h4a3 3 0 0 0 6 0h1a1 1 0 0 0 1-1v-4a1 1 0 0 0-.29-.71L18 7.59V5a1 1 0 0 0-1-1H3m14 4.41L19.59 11H17V8.41M7 15a1 1 0 0 1 1 1 1 1 0 0 1-1 1 1 1 0 0 1-1-1 1 1 0 0 1 1-1m10 0a1 1 0 0 1 1 1 1 1 0 0 1-1 1 1 1 0 0 1-1-1 1 1 0 0 1 1-1z',
			'mdi:chart-line':
				'M16 11.78l4.24-7.33 1.73 1-5.23 9.05-6.51-3.75L5.46 19H22v2H2V3h2v14.54L9.5 8z',
			'mdi:chart-bar': 'M22 21H2V3h2v16h2v-9h4v9h2V6h4v13h2v-5h4v7z',
			'mdi:account-search':
				'M10 13c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0-6c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm6.39 8.56C14.71 14.7 12.53 14 10 14s-4.71.7-6.39 1.56A2.97 2.97 0 0 0 2 18.22V21h16v-2.78c0-1.12-.61-2.15-1.61-2.66zm-.49 4.44H4.1v-.78c0-.38.2-.72.52-.88C5.71 16.73 7.63 16 10 16c2.37 0 4.29.73 5.38 1.34.32.16.52.5.52.88v.78zM19.81 18l-.93.93 2.12 2.12 1.41-1.41-2.6-2.59V12h-1.34l-2.66 2.66 1.41 1.41.93-.93V18h1.66z',
			'mdi:account-plus':
				'M15 14c-2.67 0-8 1.33-8 4v2h16v-2c0-2.67-5.33-4-8-4m0-2a4 4 0 0 0 4-4 4 4 0 0 0-4-4 4 4 0 0 0-4 4 4 4 0 0 0 4 4m-9.5 4.5v-3h-3v-2h3v-3h2v3h3v2h-3v3h-2z',
			'mdi:calendar-clock':
				'M15 13h1.5v2.82l2.44 1.41-.75 1.3L15 16.69V13m4-5H5v11h4.67c-.43-.91-.67-1.93-.67-3a7 7 0 0 1 7-7c1.07 0 2.09.24 3 .67V8M5 21a2 2 0 0 1-2-2V5c0-1.11.89-2 2-2h1V1h2v2h8V1h2v2h1a2 2 0 0 1 2 2v6.1c1.24 1.26 2 2.99 2 4.9a7 7 0 0 1-7 7c-1.91 0-3.64-.76-4.9-2H5m11-9.85A4.85 4.85 0 0 0 11.15 16c0 2.68 2.17 4.85 4.85 4.85A4.85 4.85 0 0 0 20.85 16c0-2.68-2.17-4.85-4.85-4.85z'
		};
		return (
			iconMap[icon || ''] || 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z'
		);
	}
</script>

<svelte:head>
	<title>{program?.name || 'Program'} - {clientName}</title>
</svelte:head>

<AuthGuard {auth} redirectTo="/login">
	{#snippet children()}
		<div class="bg-base-200 flex h-screen">
			<!-- Sidebar -->
			<aside
				class="bg-base-100 border-base-300 flex flex-col border-r transition-all duration-300 {sidebarCollapsed
					? 'w-[72px]'
					: 'w-64'}"
			>
				<!-- Sidebar Header -->
				<div class="border-base-200 flex items-center gap-3 border-b p-4">
					<button
						onclick={goToPrograms}
						class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-all hover:opacity-80"
						style="background: linear-gradient(135deg, {program?.color ||
							'#4F46E5'}, {program?.color || '#4F46E5'}cc)"
						title="Back to programs"
					>
						<svg class="h-5 w-5 text-white" fill="currentColor" viewBox="0 0 24 24">
							<path
								d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
							></path>
						</svg>
					</button>
					{#if !sidebarCollapsed}
						<div class="min-w-0 flex-1">
							<h2 class="text-base-content truncate font-semibold">{program?.name}</h2>
						</div>
						<button
							onclick={toggleSidebar}
							class="btn btn-ghost btn-sm btn-square"
							title="Collapse sidebar"
						>
							<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M4 6h16M4 12h16M4 18h16"
								></path>
							</svg>
						</button>
					{:else}
						<button
							onclick={toggleSidebar}
							class="btn btn-ghost btn-sm btn-square absolute left-16 top-4 opacity-0 group-hover:opacity-100"
							title="Expand sidebar"
						>
							<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M4 6h16M4 12h16M4 18h16"
								></path>
							</svg>
						</button>
					{/if}
				</div>

				<!-- Dashboard Link -->
				<div class="px-2 py-3">
					<button
						onclick={() => goto(`/program/${program.slug}`)}
						class="hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer flex w-full items-center gap-3 rounded-lg px-3 py-2.5 transition-colors {!currentModule
							? 'bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300'
							: 'text-gray-700 dark:text-gray-200'}"
						title="Dashboard"
					>
						<svg class="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
							></path>
						</svg>
						{#if !sidebarCollapsed}
							<span class="font-medium">Dashboard</span>
						{/if}
					</button>
				</div>

				<!-- Navigation -->
				<nav class="flex-1 overflow-y-auto px-2 pb-4">
					{#each modules as module, moduleIndex (module.id)}
						<!-- Section Header (when expanded) -->
						{#if !sidebarCollapsed}
							<div class="mt-2 px-3 py-2 first:mt-0">
								<span class="text-primary text-xs font-semibold uppercase tracking-wider">
									{module.name}
								</span>
							</div>
						{:else}
							<!-- Divider when collapsed -->
							{#if moduleIndex > 0}
								<div class="border-base-200 my-2 border-t"></div>
							{/if}
						{/if}

						<!-- Submodules -->
						{#each module.submodules as submodule (submodule.id)}
							<button
								onclick={() => navigateToSubmodule(module, submodule)}
								class="hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer mb-0.5 flex w-full items-center gap-3 rounded-lg px-3 py-2 transition-colors
                  {isSubmoduleActive(submodule)
									? 'bg-primary-50 text-primary-700 font-medium dark:bg-primary-900/30 dark:text-primary-300'
									: 'text-gray-700 dark:text-gray-200/80'}"
								title={sidebarCollapsed ? submodule.name : undefined}
							>
								<svg class="h-5 w-5 shrink-0" fill="currentColor" viewBox="0 0 24 24">
									<path d={getIconPath(submodule.icon)}></path>
								</svg>
								{#if !sidebarCollapsed}
									<span class="flex-1 text-left text-sm">{submodule.name}</span>
									{#if submodule.type === 'container'}
										<span class="badge badge-ghost badge-sm">2</span>
									{/if}
								{/if}
							</button>
						{/each}
					{/each}
				</nav>

				<!-- User Profile Section -->
				<div class="border-base-200 mt-auto border-t">
					<div class="p-3">
						{#if sidebarCollapsed}
							<!-- Collapsed: Just avatar -->
							<div class="dropdown dropdown-top dropdown-end flex w-full justify-center">
								<div
									tabindex="0"
									role="button"
									class="avatar cursor-pointer {user?.avatar ? '' : 'placeholder'}"
								>
									{#if user?.avatar}
										<div class="h-10 w-10 rounded-full">
											<img src={user.avatar} alt={user.displayName} />
										</div>
									{:else}
										<div
											class="bg-neutral text-neutral-content flex h-10 w-10 items-center justify-center rounded-full"
										>
											<svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24">
												<path d={userIconPath}></path>
											</svg>
										</div>
									{/if}
								</div>
								<ul
									tabindex="0"
									class="dropdown-content menu bg-base-100 rounded-box border-base-200 z-[1] mb-2 w-52 border p-2 shadow-lg"
								>
									<li class="menu-title px-2 py-1">
										<span class="text-base-content/60 text-xs"
											>{user?.email || 'user@example.com'}</span
										>
									</li>
									<li>
										<a href="/profile" class="gap-2">
											<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
												></path>
											</svg>
											View Profile
										</a>
									</li>
									<li>
										<a href="/settings" class="gap-2">
											<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
												></path>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
												></path>
											</svg>
											Settings
										</a>
									</li>
									<div class="divider my-1"></div>
									<li>
										<button onclick={handleLogout} class="text-error gap-2">
											<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
												></path>
											</svg>
											Logout
										</button>
									</li>
								</ul>
							</div>
						{:else}
							<!-- Expanded: Full profile card -->
							<div class="flex items-center gap-3">
								<div class="avatar {user?.avatar ? '' : 'placeholder'}">
									{#if user?.avatar}
										<div class="h-10 w-10 rounded-full">
											<img src={user.avatar} alt={user.displayName} />
										</div>
									{:else}
										<div
											class="bg-neutral text-neutral-content flex h-10 w-10 items-center justify-center rounded-full"
										>
											<svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24">
												<path d={userIconPath}></path>
											</svg>
										</div>
									{/if}
								</div>
								<div class="min-w-0 flex-1">
									<p class="truncate text-sm font-medium">{user?.displayName || 'User'}</p>
									<a
										href="/profile"
										class="text-base-content/60 hover:text-primary text-xs transition-colors"
									>
										view profile
									</a>
								</div>
								<div class="dropdown dropdown-top dropdown-end">
									<button tabindex="0" class="btn btn-ghost btn-sm btn-square">
										<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
											></path>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
											></path>
										</svg>
									</button>
									<ul
										tabindex="0"
										class="dropdown-content menu bg-base-100 rounded-box border-base-200 z-[1] mb-2 w-52 border p-2 shadow-lg"
									>
										<li>
											<a href="/settings" class="gap-2">
												<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														stroke-width="2"
														d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
													></path>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														stroke-width="2"
														d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
													></path>
												</svg>
												Settings
											</a>
										</li>
										<div class="divider my-1"></div>
										<li>
											<button onclick={handleLogout} class="text-error gap-2">
												<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														stroke-width="2"
														d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
													></path>
												</svg>
												Logout
											</button>
										</li>
									</ul>
								</div>
							</div>
						{/if}
					</div>
				</div>
			</aside>

			<!-- Main Area -->
			<div class="flex flex-1 flex-col overflow-hidden">
				<!-- Top Toolbar -->
				<header
					class="navbar bg-base-100 border-base-200 z-20 min-h-12 gap-2 border-b px-3 shadow-sm"
				>
					<!-- Left Section: Sidebar Toggle & Search -->
					<div class="flex items-center gap-4">
						{#if sidebarCollapsed}
							<button
								onclick={toggleSidebar}
								class="btn btn-ghost btn-sm btn-square"
								title="Expand sidebar"
							>
								<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M4 6h16M4 12h16M4 18h16"
									></path>
								</svg>
							</button>
						{/if}

						<!-- Global Search -->
						<div class="relative hidden w-64 sm:block">
							<input
								type="text"
								placeholder="Search..."
								class="input input-sm input-bordered bg-base-200/50 focus:bg-base-100 w-full pl-10 transition-all duration-300 focus:w-80"
							/>
							<svg
								class="text-base-content/50 absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
								></path>
							</svg>
						</div>
					</div>

					<!-- Middle Section: Dynamic Toolbar Buttons -->
					<div class="flex flex-1 items-center justify-center gap-2">
						{#each toolbarStore.buttons as button (button.id)}
							{#if !button.position}
								<div class="tooltip tooltip-bottom" data-tip={button.label}>
									<button
										onclick={button.onClick}
										class="btn btn-sm btn-circle {button.variant === 'primary'
											? 'btn-primary'
											: button.variant === 'secondary'
												? 'btn-secondary'
												: button.variant === 'accent'
													? 'btn-accent'
													: 'btn-ghost'}"
									>
										{#if button.icon}
											<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
												<path d={getIconPath(button.icon)}></path>
											</svg>
										{/if}
									</button>
								</div>
							{/if}
						{/each}
					</div>

					<!-- Right Section: System Actions & User Menu -->
					<div class="flex items-center gap-1 sm:gap-2">
						<!-- Right Aligned Dynamic Buttons -->
						{#each toolbarStore.buttons.filter((b) => b.position === 'right') as button (button.id)}
							<div class="tooltip tooltip-bottom" data-tip={button.label}>
								<button
									onclick={button.onClick}
									class="btn btn-sm btn-circle {button.variant === 'primary'
										? 'btn-primary'
										: button.variant === 'secondary'
											? 'btn-secondary'
											: 'btn-ghost'}"
								>
									{#if button.icon}
										<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
											<path d={getIconPath(button.icon)}></path>
										</svg>
									{/if}
								</button>
							</div>
						{/each}

						<!-- Notifications -->
						<div class="dropdown dropdown-end">
							<button tabindex="0" role="button" class="btn btn-ghost btn-circle btn-sm relative">
								<div class="indicator">
									<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
										></path>
									</svg>
									{#if notificationStore.unreadCount > 0}
										<span class="absolute top-0 right-0 block h-2.5 w-2.5 rounded-full ring-2 ring-white bg-primary"></span>
									{/if}
								</div>
							</button>
							<div
								tabindex="0"
								class="dropdown-content card card-compact bg-base-100 border-base-200 z-[1] w-80 border shadow-xl"
							>
								<div class="card-body">
									<div class="border-base-200 flex items-center justify-between border-b pb-2">
										<h3 class="text-lg font-bold">Notifications</h3>
										{#if notificationStore.unreadCount > 0}
											<button
												onclick={handleMarkAllRead}
												class="text-primary text-xs hover:underline"
											>
												Mark all read
											</button>
										{/if}
									</div>
									<div class="flex max-h-80 flex-col gap-1 overflow-y-auto">
										{#if notificationStore.notifications.length === 0}
											<div class="text-base-content/60 py-4 text-center">No notifications</div>
										{:else}
											{#each notificationStore.notifications as note (note.id)}
												<button
													class="hover:bg-base-200 relative flex gap-3 rounded-lg p-2 text-left transition-colors {note.read
														? 'opacity-60'
														: 'bg-base-200/30'}"
													onclick={() => handleNotificationClick(note.id)}
												>
													<div class="shrink-0 pt-1">
														{#if note.type === 'success'}
															<div class="bg-success h-2 w-2 rounded-full"></div>
														{:else if note.type === 'error'}
															<div class="bg-error h-2 w-2 rounded-full"></div>
														{:else if note.type === 'warning'}
															<div class="bg-warning h-2 w-2 rounded-full"></div>
														{:else}
															<div class="bg-info h-2 w-2 rounded-full"></div>
														{/if}
													</div>
													<div class="min-w-0">
														<h4 class="truncate text-sm font-medium">{note.title}</h4>
														<p class="text-base-content/70 line-clamp-2 text-xs">{note.message}</p>
														<span class="text-base-content/40 text-[10px]">
															{new Date(note.timestamp).toLocaleTimeString()}
														</span>
													</div>
													{#if !note.read}
														<div
															class="bg-primary absolute right-2 top-2 h-1.5 w-1.5 rounded-full shadow-sm"
														></div>
													{/if}
												</button>
											{/each}
										{/if}
									</div>
								</div>
							</div>
						</div>

						<!-- Theme Switcher -->
						<ThemeSwitcher />

						<!-- User Menu -->
						<div class="dropdown dropdown-end ml-2">
							<div
								tabindex="0"
								role="button"
								class="btn btn-ghost btn-circle avatar {user?.avatar ? '' : 'placeholder'}"
							>
								{#if user?.avatar}
									<div
										class="ring-base-200 ring-offset-base-100 h-9 w-9 rounded-full ring ring-offset-2"
									>
										<img src={user.avatar} alt={user.displayName} />
									</div>
								{:else}
									<div
										class="bg-neutral text-neutral-content ring-base-200 ring-offset-base-100 flex h-9 w-9 items-center justify-center rounded-full ring ring-offset-2"
									>
										<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
											<path d={userIconPath}></path>
										</svg>
									</div>
								{/if}
							</div>
							<ul
								tabindex="0"
								class="menu menu-sm dropdown-content bg-base-100 rounded-box border-base-200 z-[1] mt-3 w-52 border p-2 shadow-lg"
							>
								<li class="menu-title border-base-200 mb-2 border-b px-4 py-2">
									<div class="flex flex-col gap-0.5">
										<span class="text-base-content font-bold">{user?.displayName}</span>
										<span class="text-base-content/60 text-xs font-normal">{user?.email}</span>
									</div>
								</li>
								<li>
									<a href="/profile" class="justify-between">
										Profile
										<span class="badge badge-ghost badge-sm">New</span>
									</a>
								</li>
								<li><a href="/settings">Settings</a></li>
								<div class="divider my-1"></div>
								<li><button onclick={handleLogout} class="text-error">Logout</button></li>
							</ul>
						</div>
					</div>
				</header>

				<!-- Content Area -->
				<main class="bg-base-200/50 flex-1 overflow-auto p-1">
					<ToastContainer />
					<slot />
				</main>
			</div>
		</div>
	{/snippet}
</AuthGuard>
