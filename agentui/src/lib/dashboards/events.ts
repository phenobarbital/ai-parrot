// events.ts - Sistema de eventos tipado
import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type { Placement, AnyPlacement } from "./types.js";

export interface DashboardEvents {
    "widget:added": { widget: Widget; dashboard: DashboardView; placement: AnyPlacement };
    "widget:removed": { widget: Widget; dashboard: DashboardView };
    "widget:moved": { widget: Widget; from?: AnyPlacement; to?: AnyPlacement; paneId?: string };
    "widget:docked": { widget: Widget; dashboard: DashboardView; placement: AnyPlacement };
    "widget:floated": { widget: Widget };
    "widget:maximized": { widget: Widget };
    "widget:restored": { widget: Widget };
    "widget:minimized": { widget: Widget };
    "dashboard:activated": { dashboard: DashboardView };
    "dashboard:added": { dashboard: DashboardView };
    "dashboard:removed": { dashboard: DashboardView };
    "slideshow:start": { dashboard: DashboardView };
    "slideshow:end": { dashboard: DashboardView };
    "dock:template-changed": { template: unknown; layout: unknown };
    "dock:pane-split": { paneId: string; newPaneId: string; direction: string };
    "dock:pane-removed": { paneId: string };
}

type EventCallback<T> = (data: T) => void;

export class EventBus {
    private listeners = new Map<string, Set<EventCallback<unknown>>>();

    on<K extends keyof DashboardEvents>(
        event: K,
        callback: EventCallback<DashboardEvents[K]>
    ): () => void {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event)!.add(callback as EventCallback<unknown>);

        return () => {
            this.listeners.get(event)?.delete(callback as EventCallback<unknown>);
        };
    }

    emit<K extends keyof DashboardEvents>(event: K, data: DashboardEvents[K]): void {
        this.listeners.get(event)?.forEach(cb => cb(data));
    }

    off<K extends keyof DashboardEvents>(
        event: K,
        callback?: EventCallback<DashboardEvents[K]>
    ): void {
        if (callback) {
            this.listeners.get(event)?.delete(callback as EventCallback<unknown>);
        } else {
            this.listeners.delete(event);
        }
    }

    clear(): void {
        this.listeners.clear();
    }
}

// Singleton global para la aplicación
export const bus = new EventBus();