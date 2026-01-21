<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { auth } from '$lib/auth';
  import { clientStore } from '$lib/stores/client.svelte';
  import { themeStore } from '$lib/stores/theme.svelte.js';
  import Toast from '$lib/components/Toast.svelte';
  import '../app.css';

  // Get client from page data (server-loaded)
  $effect(() => {
    const client = $page.data.client;
    if (client) {
      clientStore.setClient(client);
      // Apply theme from client config
      if (client.theme) {
        themeStore.setTheme(client.theme);
      }
    }
  });

  // Initialize stores on mount
  onMount(() => {
    auth.init();
    themeStore.init();
  });
</script>

<div class="min-h-screen bg-base-100">
  <slot />
</div>

<!-- Global toast notifications -->
<Toast />
