export interface Notification {
    id: string;
    title: string;
    message: string;
    type: 'info' | 'success' | 'warning' | 'error';
    timestamp: Date;
    read: boolean;
    toast?: boolean; // If true, show as toast
    duration?: number; // Toast duration
}

class NotificationStore {
    notifications = $state<Notification[]>([]);

    // Derived state for unread count
    unreadCount = $derived(this.notifications.filter(n => !n.read).length);

    constructor() {
        // Load from local storage if needed? For now, in-memory.
    }

    add(notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) {
        const newNotification: Notification = {
            ...notification,
            id: crypto.randomUUID(),
            timestamp: new Date(),
            read: false,
        };

        // Add to beginning of list
        this.notifications = [newNotification, ...this.notifications];

        // Limit history size
        if (this.notifications.length > 50) {
            this.notifications = this.notifications.slice(0, 50);
        }

        return newNotification;
    }

    markAsRead(id: string) {
        const index = this.notifications.findIndex(n => n.id === id);
        if (index !== -1) {
            this.notifications[index].read = true;
        }
    }

    markAllAsRead() {
        this.notifications.forEach(n => n.read = true);
    }

    remove(id: string) {
        this.notifications = this.notifications.filter(n => n.id !== id);
    }
}

export const notificationStore = new NotificationStore();

// Helper for quick toast
export function addToast(message: string, type: 'info' | 'success' | 'warning' | 'error' = 'info', duration = 3000) {
    notificationStore.add({
        title: type.charAt(0).toUpperCase() + type.slice(1),
        message,
        type,
        toast: true,
        duration
    });
}
