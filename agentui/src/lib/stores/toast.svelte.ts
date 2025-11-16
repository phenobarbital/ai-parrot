import { writable } from 'svelte/store';

type ToastType = 'success' | 'error' | 'info';

export type ToastMessage = {
  id: string;
  type: ToastType;
  message: string;
  duration: number;
};

function createToastStore() {
  const { subscribe, update } = writable<ToastMessage[]>([]);

  function push(type: ToastType, message: string, duration = 3000) {
    const id = crypto.randomUUID();
    update((toasts) => [...toasts, { id, type, message, duration }]);
    setTimeout(() => {
      update((toasts) => toasts.filter((toast) => toast.id !== id));
    }, duration);
  }

  return {
    subscribe,
    success: (message: string, duration?: number) => push('success', message, duration),
    error: (message: string, duration?: number) => push('error', message, duration),
    info: (message: string, duration?: number) => push('info', message, duration)
  };
}

export const toastStore = createToastStore();
