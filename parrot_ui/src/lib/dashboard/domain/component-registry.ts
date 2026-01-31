/**
 * Component Registry
 * 
 * Maps component names to their Svelte component constructors.
 * Register all components that can be used in 'component' layout mode here.
 */

import type { Component } from 'svelte';

// Import module components
import SimpleForm from '../components/modules/SimpleForm.svelte';

// Registry type
// Component registry - add new components here
export const COMPONENT_REGISTRY = {
    'SimpleForm': SimpleForm,
    // Add more components as needed
    // 'FileManager': FileManager,
    // 'DataTable': DataTable,
} as const satisfies Record<string, Component>;

export type ComponentRegistry = typeof COMPONENT_REGISTRY;
export type ComponentName = keyof ComponentRegistry;

/**
 * Get a component from the registry by name
 */
export function getComponent<Name extends ComponentName>(name: Name): ComponentRegistry[Name];
export function getComponent(name: string): Component | undefined;
export function getComponent(name: string): Component | undefined {
    return (COMPONENT_REGISTRY as Record<string, Component>)[name];
}

/**
 * Get all available component names
 */
export function getAvailableComponents(): ComponentName[] {
    return Object.keys(COMPONENT_REGISTRY) as ComponentName[];
}
