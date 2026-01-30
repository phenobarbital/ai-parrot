<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { auth } from '$lib/auth';
	import { toastStore } from '$lib/stores/toast.svelte';
	import { LoadingSpinner, ThemeSwitcher } from '$components';
	import { ProviderButtons } from '$lib/navauth';
	import { config } from '$lib/config';

	let username = $state(config.defaultUsername);
	let password = $state(config.defaultPassword);
	let error = $state('');
	let loading = $state(false);
	let showPassword = $state(false);

	// Get client from page data
	const client = $derived($page.data.client);
	const clientName = $derived(client?.name || config.appName);
	const clientLogo = $derived(client?.logo);

	// Redirect if already authenticated
	// Redirect if already authenticated and handle Carousel
	const backgroundImages = [1, 2, 3, 4].map((n) => `/images/navigator/login/image-${n}.png`);
	let currentImageIndex = $state(0);

	onMount(() => {
		const interval = setInterval(() => {
			currentImageIndex = (currentImageIndex + 1) % backgroundImages.length;
		}, 2000);

		const unsubscribe = auth.subscribe((state) => {
			if (state.isAuthenticated) {
				goto('/programs');
			}
		});

		return () => {
			clearInterval(interval);
			unsubscribe();
		};
	});

	async function handleSubmit(event: Event) {
		event.preventDefault();
		error = '';
		loading = true;

		const result = await auth.loginBasic(username, password);

		if (!result.success) {
			error = result.error || 'Login failed';
			loading = false;
			toastStore.error(error, 5000);
		} else {
			loading = false;
			toastStore.success('Login successful! Redirecting...', 2000);
			goto('/programs');
		}
	}

	function togglePasswordVisibility() {
		showPassword = !showPassword;
	}
</script>

<svelte:head>
	<title>Login - {clientName}</title>
</svelte:head>

<div class="bg-base-200 relative flex min-h-screen items-center justify-center overflow-hidden">
	{#each backgroundImages as image, i}
		<div
			class="absolute inset-0 bg-cover bg-center transition-opacity duration-1000"
			style="background-image: url('{image}'); opacity: {i === currentImageIndex ? 1 : 0};"
		></div>
	{/each}

	<!-- Background gradient effect -->
	<div
		class="from-primary/20 via-base-200 to-secondary/20 absolute inset-0 bg-gradient-to-br"
	></div>

	<!-- Animated background circles -->
	<div
		class="bg-primary/10 absolute -left-20 -top-20 h-96 w-96 animate-pulse rounded-full blur-3xl"
	></div>
	<div
		class="bg-secondary/10 absolute -bottom-20 -right-20 h-96 w-96 animate-pulse rounded-full blur-3xl delay-700"
	></div>

	<!-- Theme switcher -->
	<div class="absolute right-4 top-4 z-20">
		<ThemeSwitcher />
	</div>

	<div class="relative z-10 w-full max-w-md px-4 py-12">
		<!-- Logo/Title -->
		<div class="mb-8 text-center">
			{#if clientLogo}
				<img src={clientLogo} alt={clientName} class="mx-auto mb-4 h-16 w-auto" />
			{:else}
				<div class="mb-4 flex items-center justify-center">
					<div
						class="from-primary to-secondary flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br shadow-lg"
					>
						<svg
							class="text-primary-content h-10 w-10"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
							></path>
						</svg>
					</div>
				</div>
			{/if}
			<div class="mb-4 inline-block rounded-xl bg-base-100/60 px-6 py-2 backdrop-blur-md">
				<h1
					class="from-primary to-secondary bg-gradient-to-r bg-clip-text text-4xl font-bold text-transparent"
				>
					{clientName}
				</h1>
			</div>
			<p class="text-base-content/70">Welcome back! Sign in to continue.</p>
		</div>

		<!-- Login Card with glassmorphism -->
		<div class="card bg-base-100/80 border-base-content/5 border shadow-2xl backdrop-blur-xl">
			<div class="card-body">
				{#if error}
					<div class="mb-4 text-center">
						<span class="text-error font-medium">{error}</span>
					</div>
				{/if}

				<form onsubmit={handleSubmit} class="space-y-5">
					<!-- Username -->
					<div class="form-control">
						<label class="label" for="username">
							<span class="label-text font-medium">Email or Username</span>
						</label>
						<div class="relative">
							<span class="text-base-content/50 absolute left-3 top-1/2 -translate-y-1/2">
								<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
									></path>
								</svg>
							</span>
							<input
								id="username"
								type="text"
								placeholder="Enter your email or username"
								class="input input-bordered focus:input-primary w-full pl-10"
								bind:value={username}
								disabled={loading}
								required
								autocomplete="username"
							/>
						</div>
					</div>

					<!-- Password -->
					<div class="form-control">
						<label class="label" for="password">
							<span class="label-text font-medium">Password</span>
						</label>
						<div class="relative">
							<span class="text-base-content/50 absolute left-3 top-1/2 -translate-y-1/2">
								<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
									></path>
								</svg>
							</span>
							<input
								id="password"
								type={showPassword ? 'text' : 'password'}
								placeholder="Enter your password"
								class="input input-bordered focus:input-primary w-full pl-10 pr-12"
								bind:value={password}
								disabled={loading}
								required
								autocomplete="current-password"
							/>
							<button
								type="button"
								class="btn btn-ghost btn-sm absolute right-1 top-1/2 -translate-y-1/2"
								onclick={togglePasswordVisibility}
								tabindex={-1}
								aria-label={showPassword ? 'Hide password' : 'Show password'}
							>
								{#if showPassword}
									<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.542 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
										></path>
									</svg>
								{:else}
									<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
										></path>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
										></path>
									</svg>
								{/if}
							</button>
						</div>
						<div class="label">
							<a href="/forgot-password" class="link-hover link label-text-alt text-primary">
								Forgot password?
							</a>
						</div>
					</div>

					<!-- Submit Button -->
					<button
						type="submit"
						class="btn btn-primary shadow-primary/25 hover:shadow-primary/40 w-full gap-2 shadow-lg transition-all duration-300"
						disabled={loading}
					>
						{#if loading}
							<LoadingSpinner size="sm" text="" center={false} />
							Signing in...
						{:else}
							<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"
								></path>
							</svg>
							Sign In
						{/if}
					</button>
				</form>

				<!-- Divider -->
				<div class="divider text-base-content/50">OR</div>

				<!-- Additional info -->
				<div class="text-center">
					<p class="text-base-content/60 text-sm">Use your {clientName} credentials to sign in</p>
				</div>

				<ProviderButtons
					{auth}
					onSuccess={() => goto('/programs')}
					onError={(err) => (error = err)}
					dividerText="OR"
				/>
			</div>
		</div>

		<!-- Footer -->
		<div class="text-base-content/50 mt-8 text-center text-sm">
			<p>© {new Date().getFullYear()} {clientName}. All rights reserved.</p>
		</div>
	</div>
</div>

<style>
	@keyframes pulse {
		0%,
		100% {
			opacity: 0.4;
			transform: scale(1);
		}
		50% {
			opacity: 0.6;
			transform: scale(1.05);
		}
	}

	.animate-pulse {
		animation: pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}

	.delay-700 {
		animation-delay: 700ms;
	}
</style>
