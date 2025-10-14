<script>
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth.svelte.js';
  import Toast from '$lib/components/Toast.svelte';
  import '../app.css';

  // Initialize auth store on mount
  onMount(() => {
    authStore.init();
  });
</script>

<div class="min-h-screen">
  <slot />
</div>

<!-- Global toast notifications -->
<Toast />
