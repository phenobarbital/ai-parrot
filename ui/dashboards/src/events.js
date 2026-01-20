export class EventBus {
    listeners = new Map();
    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event).add(callback);
        return () => {
            this.listeners.get(event)?.delete(callback);
        };
    }
    emit(event, data) {
        this.listeners.get(event)?.forEach(cb => cb(data));
    }
    off(event, callback) {
        if (callback) {
            this.listeners.get(event)?.delete(callback);
        }
        else {
            this.listeners.delete(event);
        }
    }
    clear() {
        this.listeners.clear();
    }
}
// Singleton global para la aplicación
export const bus = new EventBus();
//# sourceMappingURL=events.js.map