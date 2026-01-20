import type { Widget } from "./widget.js";
import type { DashboardView } from "./dashboard.js";
import type { AnyPlacement } from "./types.js";
export interface DashboardEvents {
    "widget:added": {
        widget: Widget;
        dashboard: DashboardView;
        placement: AnyPlacement;
    };
    "widget:removed": {
        widget: Widget;
        dashboard: DashboardView;
    };
    "widget:moved": {
        widget: Widget;
        from?: AnyPlacement;
        to?: AnyPlacement;
        paneId?: string;
    };
    "widget:docked": {
        widget: Widget;
        dashboard: DashboardView;
        placement: AnyPlacement;
    };
    "widget:floated": {
        widget: Widget;
    };
    "widget:maximized": {
        widget: Widget;
    };
    "widget:restored": {
        widget: Widget;
    };
    "widget:minimized": {
        widget: Widget;
    };
    "dashboard:activated": {
        dashboard: DashboardView;
    };
    "dashboard:added": {
        dashboard: DashboardView;
    };
    "dashboard:removed": {
        dashboard: DashboardView;
    };
    "slideshow:start": {
        dashboard: DashboardView;
    };
    "slideshow:end": {
        dashboard: DashboardView;
    };
    "dock:template-changed": {
        template: unknown;
        layout: unknown;
    };
    "dock:pane-split": {
        paneId: string;
        newPaneId: string;
        direction: string;
    };
    "dock:pane-removed": {
        paneId: string;
    };
}
type EventCallback<T> = (data: T) => void;
export declare class EventBus {
    private listeners;
    on<K extends keyof DashboardEvents>(event: K, callback: EventCallback<DashboardEvents[K]>): () => void;
    emit<K extends keyof DashboardEvents>(event: K, data: DashboardEvents[K]): void;
    off<K extends keyof DashboardEvents>(event: K, callback?: EventCallback<DashboardEvents[K]>): void;
    clear(): void;
}
export declare const bus: EventBus;
export {};
//# sourceMappingURL=events.d.ts.map