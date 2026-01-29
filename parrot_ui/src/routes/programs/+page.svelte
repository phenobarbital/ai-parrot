<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { auth } from '$lib/auth';
	import { AuthGuard } from '$lib/navauth';
	import { notificationStore } from '$lib/stores/notifications.svelte';
	import { ThemeSwitcher } from '$components';
	import type { Program } from '$lib/types';

	// Get programs from page data
	const programs = $derived(($page.data.programs as Program[]) || []);
	const client = $derived($page.data.client);
	const clientName = $derived(client?.name || 'AI Parrot');

	// User info
	let user = $state<{ displayName: string; email: string } | null>(null);

	onMount(() => {
		const unsubscribe = auth.subscribe((state) => {
			if (state.user) {
				user = {
					displayName: state.user.displayName,
					email: state.user.email
				};
			}
		});
		return unsubscribe;
	});

	function navigateToProgram(program: Program) {
		goto(`/program/${program.slug}`);
	}

	async function handleLogout() {
		auth.logout();
		goto('/login');
	}

	function getIconPath(icon?: string): string {
		// Map common icon names to SVG paths
		const iconMap: Record<string, string> = {
			'mdi:store':
				'M3 13h1v7c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-7h1a1 1 0 0 0 .7-1.7l-9-9a1 1 0 0 0-1.4 0l-9 9A1 1 0 0 0 3 13z',
			'mdi:account-tie':
				'M12 3c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm-2 16h4v-6h3l-5-5-5 5h3v6z',
			'mdi:currency-usd':
				'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1.41 16.09V20h-2v-1.93c-1.44-.35-2.66-1.23-2.82-2.73h1.67c.13.81.85 1.41 2.15 1.41 1.42 0 2-.73 2-1.19 0-.62-.42-1.18-2.17-1.64-1.94-.5-3.22-1.36-3.22-2.92 0-1.47 1.22-2.52 2.39-2.86V6h2v1.93c1.53.45 2.35 1.57 2.43 2.73h-1.68c-.09-.77-.63-1.41-1.75-1.41-1.05 0-1.83.53-1.83 1.19 0 .54.35 1.12 1.97 1.56 1.8.48 3.42 1.2 3.42 2.93-.01 1.52-1.23 2.58-2.56 2.92z',
			'mdi:chart-bubble':
				'M7.2 11.2c-1.32 0-2.4 1.08-2.4 2.4s1.08 2.4 2.4 2.4 2.4-1.08 2.4-2.4-1.08-2.4-2.4-2.4zm9.6-5.6c-1.54 0-2.8 1.26-2.8 2.8s1.26 2.8 2.8 2.8 2.8-1.26 2.8-2.8-1.26-2.8-2.8-2.8zM12 12c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z',
			'mdi:compass':
				'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 12.14v1.14c0 1.1.9 2 2 2v3.59c0 .36.35.62.7.53l.3-.07V19.93zM17.9 17.39c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1h-6v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z'
		};
		return (
			iconMap[icon || ''] || 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z'
		);
	}
</script>

<svelte:head>
	<title>Programs - {clientName}</title>
</svelte:head>

<AuthGuard {auth} redirectTo="/login">
	{#snippet children()}
		<div class="from-base-200 via-base-100 to-base-200 min-h-screen bg-gradient-to-br">
			<!-- Top bar -->
			<header
				class="navbar bg-base-100/80 border-base-content/5 sticky top-0 z-50 border-b shadow-sm backdrop-blur-lg"
			>
				<div class="flex-1">
					<div class="flex items-center gap-3">
						<div
							class="from-primary to-secondary flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br"
						>
							<svg
								class="text-primary-content h-6 w-6"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
								></path>
							</svg>
						</div>
						<div>
							<h1 class="text-lg font-bold">{clientName}</h1>
							<p class="text-base-content/60 text-xs">Select a program</p>
						</div>
					</div>
				</div>
				<div class="flex flex-none items-center gap-2">
					<!-- Notification Bell -->
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
									<span class="badge badge-xs badge-primary indicator-item"></span>
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
											onclick={() => notificationStore.markAllAsRead()}
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
												onclick={() => notificationStore.markAsRead(note.id)}
											>
												<div class="min-w-0">
													<h4 class="truncate text-sm font-medium">{note.title}</h4>
													<p class="text-base-content/70 line-clamp-2 text-xs">{note.message}</p>
												</div>
											</button>
										{/each}
									{/if}
								</div>
							</div>
						</div>
					</div>

					<ThemeSwitcher />

					<!-- User Avatar -->
					<div class="dropdown dropdown-end ml-2">
						<div tabindex="0" role="button" class="btn btn-ghost btn-circle avatar placeholder">
							<div
								class="bg-neutral text-neutral-content ring-base-200 ring-offset-base-100 flex h-9 w-9 items-center justify-center rounded-full ring ring-offset-2"
							>
								<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
									<path
										d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"
									></path>
								</svg>
							</div>
						</div>
						<ul
							tabindex="0"
							class="menu menu-sm dropdown-content bg-base-100 rounded-box border-base-content/5 z-[1] mt-3 w-52 border p-2 shadow-lg"
						>
							<li class="menu-title px-4 py-2">
								<span class="text-base-content/60 text-xs">{user?.email || 'user@example.com'}</span
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
									Profile
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
				</div>
			</header>

			<!-- Main content -->
			<main class="container mx-auto px-4 py-8">
				<div class="mb-8">
					<h2 class="mb-2 text-3xl font-bold">Your Programs</h2>
					<p class="text-base-content/60">Choose a program to get started</p>
				</div>

				<!-- Programs Grid -->
				<div class="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
					{#each programs as program (program.id)}
						<button
							onclick={() => navigateToProgram(program)}
							class="card bg-base-100 border-base-content/5 group cursor-pointer border shadow-lg transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
						>
							<figure class="px-6 pt-6">
								<div
									class="flex h-20 w-20 items-center justify-center rounded-2xl transition-transform group-hover:scale-110"
									style="background: linear-gradient(135deg, {program.color ||
										'#6366F1'}, {program.color || '#6366F1'}88)"
								>
									<svg class="h-10 w-10 text-white" fill="currentColor" viewBox="0 0 24 24">
										<path d={getIconPath(program.icon)}></path>
									</svg>
								</div>
							</figure>
							<div class="card-body items-center text-center">
								<h3 class="card-title text-lg">{program.name}</h3>
								<p class="text-base-content/60 line-clamp-2 text-sm">
									{program.description || 'No description available'}
								</p>
								<div class="card-actions mt-2">
									<span class="badge badge-ghost badge-sm"
										>{program.modules?.length || 0} modules</span
									>
								</div>
							</div>
						</button>
					{/each}

					{#if programs.length === 0}
						<div class="col-span-full flex flex-col items-center justify-center py-16 text-center">
							<div class="bg-base-200 mb-4 flex h-24 w-24 items-center justify-center rounded-full">
								<svg
									class="text-base-content/30 h-12 w-12"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
									></path>
								</svg>
							</div>
							<h3 class="mb-2 text-lg font-semibold">No Programs Available</h3>
							<p class="text-base-content/60 max-w-sm">
								There are no programs assigned to your account. Please contact your administrator.
							</p>
						</div>
					{/if}
				</div>
			</main>
		</div>
	{/snippet}
</AuthGuard>
