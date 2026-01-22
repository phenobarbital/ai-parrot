<!-- src/lib/navauth/components/ProviderButtons.svelte -->
<script lang="ts">
	import type { NavAuthStore } from '../store.svelte';
	import type { AuthMethod } from '../types';

	interface Props {
		auth: NavAuthStore;
		exclude?: AuthMethod[];
		onSuccess?: () => void;
		onError?: (error: string) => void;
		dividerText?: string;
	}

	let {
		auth,
		exclude = ['basic'],
		onSuccess,
		onError,
		dividerText = 'Or continue with'
	}: Props = $props();

	let loading = $state<string | null>(null);

	// Filter out excluded providers
	const providers = $derived(auth.enabledProviders.filter((p) => !exclude.includes(p.name)));

	const providerIcons: Record<string, string> = {
		google: `<svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>`,
		microsoft: `<svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#f25022" d="M1 1h10v10H1z"/><path fill="#00a4ef" d="M1 13h10v10H1z"/><path fill="#7fba00" d="M13 1h10v10H13z"/><path fill="#ffb900" d="M13 13h10v10H13z"/></svg>`,
		sso: `<svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>`,
		azure: `<svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#0072c6" d="M1.14 6.72l4.33 2.1L14.6 3.42l-2.42-2.3L1.14 6.72zm11.04 13.86l2.42 2.3 11.04-5.6-4.33-2.1L12.18 20.58zM12.18 3.42l8.83 8.58 4.33-2.1-11.04-5.6-2.12-.88zM4.33 13.11l11.04 5.6 2.12-.88L8.66 9.25l-4.33 2.1-.03 1.76z"/></svg>`,
		adfs: `<svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>`
	};

	async function handleClick(providerName: string) {
		loading = providerName;

		const result = await auth.login(providerName);

		// OAuth providers return redirect_initiated
		if (result.error === 'redirect_initiated') {
			return; // Page will redirect
		}

		loading = null;

		if (result.success) {
			onSuccess?.();
		} else if (result.error) {
			onError?.(result.error);
		}
	}
</script>

{#if providers.length > 0}
	<div class="divider text-base-content/60 text-sm">{dividerText}</div>

	<div class="flex flex-col gap-2">
		{#each providers as provider}
			<button
				type="button"
				class="btn btn-outline w-full gap-2"
				disabled={loading !== null}
				onclick={() => handleClick(provider.name)}
			>
				{#if loading === provider.name}
					<span class="loading loading-spinner loading-sm"></span>
				{:else}
					{@html providerIcons[provider.name] || ''}
				{/if}
				{provider.label || `Sign in with ${provider.name}`}
			</button>
		{/each}
	</div>
{/if}
