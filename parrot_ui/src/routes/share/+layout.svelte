<script lang="ts">
	import Toast from '$lib/components/Toast.svelte';
	import { onMount } from 'svelte';
	import { themeStore } from '$lib/stores/theme.svelte';
    import '../../app.css';

	onMount(() => {
		themeStore.init();
	});
</script>

<div class="min-h-screen bg-base-100">
	<slot />
</div>

<Toast />
