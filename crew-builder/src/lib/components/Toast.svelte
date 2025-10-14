<script>
  import { toastStore } from '$lib/stores/toast.svelte';

  function getAlertClass(type) {
    switch (type) {
      case 'success':
        return 'alert-success';
      case 'error':
        return 'alert-error';
      case 'warning':
        return 'alert-warning';
      case 'info':
      default:
        return 'alert-info';
    }
  }

  function getIcon(type) {
    switch (type) {
      case 'success':
        return `
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        `;
      case 'error':
        return `
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        `;
      case 'warning':
        return `
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        `;
      case 'info':
      default:
        return `
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        `;
    }
  }
</script>

<div class="toast toast-top toast-end z-50">
  {#each toastStore.toasts as toast (toast.id)}
    <div class="alert {getAlertClass(toast.type)} shadow-lg">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        class="h-6 w-6 shrink-0 stroke-current"
        fill="none"
        viewBox="0 0 24 24"
      >
        {@html getIcon(toast.type)}
      </svg>
      <span>{toast.message}</span>
      {#if toast.dismissible}
        <button
          class="btn btn-ghost btn-sm btn-circle"
          onclick={() => toastStore.remove(toast.id)}
        >
          ✕
        </button>
      {/if}
    </div>
  {/each}
</div>
