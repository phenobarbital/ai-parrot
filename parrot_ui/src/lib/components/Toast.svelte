<script lang="ts">
  import { toastStore, type ToastMessage } from '$lib/stores/toast.svelte.ts';

  let toasts = $state<ToastMessage[]>([]);

  $effect(() => {
    const unsubscribe = toastStore.subscribe((items) => {
      toasts = items;
    });

    return () => unsubscribe();
  });
</script>

<div class="toast toast-end z-[1000]">
  {#each toasts as toast (toast.id)}
    <div class={`alert alert-${toast.type}`}>
      <span>{toast.message}</span>
    </div>
  {/each}
</div>
