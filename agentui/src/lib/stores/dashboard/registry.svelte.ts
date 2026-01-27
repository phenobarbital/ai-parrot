
import type { Component } from 'svelte';

export interface WidgetDefinition {
    type: string;
    name: string;
    icon: string;
    description: string;
    component?: Component<any>; // Svelte component
    defaultConfig?: any;
}

export class WidgetRegistry {
    private definitions = new Map<string, WidgetDefinition>();

    constructor() {
        // Register default types if needed, or let them be registered externally
    }

    register(def: WidgetDefinition) {
        this.definitions.set(def.type, def);
    }

    get(type: string): WidgetDefinition | undefined {
        return this.definitions.get(type);
    }

    getAll(): WidgetDefinition[] {
        return Array.from(this.definitions.values());
    }
}

export const registry = new WidgetRegistry();
