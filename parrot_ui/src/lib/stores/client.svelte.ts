// src/lib/stores/client.svelte.ts

/**
 * Client Context Store
 * Manages the current client, program, module, and submodule state
 */

import { writable, derived, get } from 'svelte/store';
import type { Client, Program, Module, Submodule, NavigationContext } from '$lib/types';
import { getClientBySlug, getProgramBySlug, getModuleBySlug, getSubmoduleBySlug } from '$lib/data/mock-data';

interface ClientState {
    loading: boolean;
    client: Client | null;
    currentProgram: Program | null;
    currentModule: Module | null;
    currentSubmodule: Submodule | null;
    error: string | null;
}

function createClientStore() {
    const state = writable<ClientState>({
        loading: true,
        client: null,
        currentProgram: null,
        currentModule: null,
        currentSubmodule: null,
        error: null
    });

    /**
     * Initialize store with client data (called from server-side)
     */
    function setClient(client: Client | null) {
        state.update((s) => ({
            ...s,
            loading: false,
            client,
            error: client ? null : 'Client not found'
        }));
    }

    /**
     * Set the current program
     */
    function setProgram(program: Program | null) {
        state.update((s) => ({
            ...s,
            currentProgram: program,
            currentModule: null,
            currentSubmodule: null
        }));
    }

    /**
     * Set the current module
     */
    function setModule(module: Module | null) {
        state.update((s) => ({
            ...s,
            currentModule: module,
            currentSubmodule: null
        }));
    }

    /**
     * Set the current submodule
     */
    function setSubmodule(submodule: Submodule | null) {
        state.update((s) => ({
            ...s,
            currentSubmodule: submodule
        }));
    }

    /**
     * Navigate to a specific path and update state
     */
    function navigateTo(programSlug?: string, moduleSlug?: string, submoduleSlug?: string) {
        state.update((s) => {
            if (!s.client) return s;

            let program: Program | null = null;
            let module: Module | null = null;
            let submodule: Submodule | null = null;

            if (programSlug) {
                program = getProgramBySlug(s.client, programSlug) || null;
                if (program && moduleSlug) {
                    module = getModuleBySlug(program, moduleSlug) || null;
                    if (module && submoduleSlug) {
                        submodule = getSubmoduleBySlug(module, submoduleSlug) || null;
                    }
                }
            }

            return {
                ...s,
                currentProgram: program,
                currentModule: module,
                currentSubmodule: submodule
            };
        });
    }

    /**
     * Get navigation context
     */
    function getNavigationContext(): NavigationContext {
        const s = get(state);
        return {
            client: s.client,
            program: s.currentProgram,
            module: s.currentModule,
            submodule: s.currentSubmodule
        };
    }

    /**
     * Get available programs for current client
     */
    const programs = derived(state, ($s) => $s.client?.programs.filter((p) => p.enabled !== false) ?? []);

    /**
     * Get modules for current program
     */
    const modules = derived(state, ($s) => $s.currentProgram?.modules ?? []);

    /**
     * Get submodules for current module
     */
    const submodules = derived(state, ($s) => $s.currentModule?.submodules ?? []);

    /**
     * Get client theme
     */
    const theme = derived(state, ($s) => $s.client?.theme ?? 'dark');

    return {
        subscribe: state.subscribe,
        setClient,
        setProgram,
        setModule,
        setSubmodule,
        navigateTo,
        getNavigationContext,
        // Derived stores
        programs,
        modules,
        submodules,
        theme,
        // Direct access helpers
        getClient: () => get(state).client,
        getProgram: () => get(state).currentProgram,
        getModule: () => get(state).currentModule,
        getSubmodule: () => get(state).currentSubmodule
    };
}

export const clientStore = createClientStore();
export type ClientStore = ReturnType<typeof createClientStore>;
