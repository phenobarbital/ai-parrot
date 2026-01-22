<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth';
	import { toastStore } from '$lib/stores/toast.svelte';

	let processing = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		const params = $page.url.searchParams;
		const token = params.get('token');
		const type = params.get('type');

		if (!token) {
			error = 'No token received from authentication provider.';
			processing = false;
			setTimeout(() => goto('/login?error=missing_token'), 2000);
			return;
		}

		try {
			// Determinar el provider (default: azure)
			const provider = params.get('provider') || 'azure';

			// Intentamos procesar el callback via auth store
			const result = await auth.login(provider, params);

			if (result.success) {
				toastStore.success('SSO Login successful!', 2000);
				goto('/programs');
			} else {
				error = result.error || 'Authentication failed.';
				processing = false;
				toastStore.error(error, 5000);
				setTimeout(() => goto('/login'), 3000);
			}
		} catch (e: any) {
			error = e.message || 'An unexpected error occurred during SSO callback.';
			processing = false;
			toastStore.error(error, 5000);
			setTimeout(() => goto('/login'), 3000);
		}
	});
</script>

<svelte:head>
	<title>Authenticating... - AI Parrot</title>
</svelte:head>

<div class="bg-base-200 flex min-h-screen flex-col items-center justify-center p-4">
	<div class="card bg-base-100 w-full max-w-md shadow-xl">
		<div class="card-body items-center text-center">
			{#if processing}
				<h2 class="card-title mb-4 text-2xl font-bold">Completing Login</h2>
				<div class="loading loading-spinner loading-lg text-primary mb-4"></div>
				<p class="text-base-content/70">Please wait while we verify your session...</p>
			{:else if error}
				<div class="bg-error/10 text-error mb-4 flex items-center gap-3 rounded-lg p-4">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
						/>
					</svg>
					<span class="font-medium">{error}</span>
				</div>
				<p class="text-base-content/60">Redirecting back to login...</p>
			{/if}
		</div>
	</div>
</div>
