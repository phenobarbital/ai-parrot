import { browser } from '$app/environment';

export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  duration: number;
  dismissible: boolean;
}

class ToastStore {
  toasts = $state<Toast[]>([]);

  private generateId(): string {
    return `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  add(message: string, type: ToastType = 'info', duration: number = 5000, dismissible: boolean = true) {
    if (!browser) return;

    const id = this.generateId();
    const toast: Toast = {
      id,
      message,
      type,
      duration,
      dismissible
    };

    this.toasts = [...this.toasts, toast];

    if (duration > 0) {
      setTimeout(() => {
        this.remove(id);
      }, duration);
    }

    return id;
  }

  remove(id: string) {
    this.toasts = this.toasts.filter((t) => t.id !== id);
  }

  clear() {
    this.toasts = [];
  }

  // Convenience methods
  info(message: string, duration?: number) {
    return this.add(message, 'info', duration);
  }

  success(message: string, duration?: number) {
    return this.add(message, 'success', duration);
  }

  warning(message: string, duration?: number) {
    return this.add(message, 'warning', duration);
  }

  error(message: string, duration?: number) {
    return this.add(message, 'error', duration);
  }
}

export const toastStore = new ToastStore();
