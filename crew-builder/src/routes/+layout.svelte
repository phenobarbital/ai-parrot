<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { themeStore } from '$lib/stores/theme.svelte.js';
  import { authStore } from '$lib/stores/auth.svelte.js';

  onMount(() => {
    themeStore.init();
    authStore.init();
  });
</script>

<div class="min-h-screen bg-base-200 text-base-content">
  <slot />
</div>
