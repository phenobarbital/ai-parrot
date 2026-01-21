import { addToast as notifyToast } from './notifications.svelte';

export const addToast = (message: string, type: 'info' | 'success' | 'warning' | 'error' = 'info', duration = 3000) => {
    notifyToast(message, type, duration);
};
