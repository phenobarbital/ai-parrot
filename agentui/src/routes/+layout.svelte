<script>
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth.svelte.ts';
  import { themeStore } from '$lib/stores/theme.svelte.js';
  import Toast from '$lib/components/Toast.svelte';
  import '../app.css';

  // Initialize stores on mount
  onMount(() => {
    authStore.init();
    themeStore.init(); // Initialize theme store
  });
</script>

<div class="min-h-screen">
  <slot />
</div>

<!-- Global toast notifications -->
<Toast />
