<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { auth } from '$lib/auth';

	// Redirect based on authentication state
	onMount(() => {
		const unsubscribe = auth.subscribe((state) => {
			if (!state.loading) {
				if (state.isAuthenticated) {
					goto('/programs');
				} else {
					goto('/login');
				}
			}
		});
		return unsubscribe;
	});
</script>

<div class="bg-base-200 flex min-h-screen items-center justify-center">
	<span class="loading loading-spinner loading-lg text-primary"></span>
</div>
