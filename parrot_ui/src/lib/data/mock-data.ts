// src/lib/data/mock-data.ts

/**
 * Mock Data for Development
 * Simulates API responses for clients, programs, modules, and submodules
 */

import type { Client, Program, Module, Submodule } from '$lib/types';
import { config } from '$lib/config';

// Finance Submodules
const financeAgentsSubmodules: Submodule[] = [
    {
        id: 'sub-fin-troc',
        slug: 'troc-finance',
        name: 'TROC Finance',
        description: 'Finance Assistant',
        icon: 'mdi:finance',
        type: 'component',
        path: 'agents/AgentChat.svelte',
        parameters: {
            agent_name: 'troc_finance'
        },
        order: 1
    }
];

// Operations Submodules
const operationsChatSubmodules: Submodule[] = [
    {
        id: 'sub-ops-chat',
        slug: 'hr_agent',
        name: 'Operations Chat',
        description: 'Chat with the Operations assistant',
        icon: 'mdi:robot-outline',
        type: 'component',
        path: 'agents/AgentChat.svelte',
        parameters: {
            agent_name: 'hr_agent'
        },
        order: 1
    }
];

// Demo Submodules
const demoSubmodules: Submodule[] = [
    {
        id: 'sub-ops-demo-dashboard',
        slug: 'demo',
        name: 'Demo Dashboard',
        description: 'Dashboard demo with widgets',
        icon: 'mdi:view-dashboard',
        type: 'component',
        path: 'modules/Demo/DemoDashboard.svelte',
        order: 1
    }
];

// Finance Modules
const financeModules: Module[] = [
    {
        id: 'mod-fin-agents',
        slug: 'agents',
        name: 'Agents',
        description: 'Finance AI Agents',
        icon: 'mdi:robot',
        submodules: financeAgentsSubmodules,
        order: 1
    },
    {
        id: 'mod-fin-kpis',
        slug: 'kpis',
        name: 'KPIs',
        description: 'Key Performance Indicators',
        icon: 'mdi:chart-box',
        submodules: [], // Empty for now
        order: 2
    }
];

// Operations Modules
const operationsModules: Module[] = [
    {
        id: 'mod-ops-chat',
        slug: 'operations-chat',
        name: 'Operations Chat',
        description: 'Operations Chat Interface',
        icon: 'mdi:forum',
        submodules: operationsChatSubmodules,
        order: 1
    },
    {
        id: 'mod-ops-demo',
        slug: 'demo',
        name: 'Demo',
        description: 'Dashboard Demo',
        icon: 'mdi:view-dashboard',
        submodules: demoSubmodules,
        order: 2
    }
];

// Sample Programs
const epsonPrograms: Program[] = [
    {
        id: 'prog-finance',
        slug: 'finance',
        name: 'Finance',
        description: 'Financial management and accounting',
        icon: 'mdi:currency-usd',
        color: '#F59E0B',
        modules: financeModules,
        enabled: true
    },
    {
        id: 'prog-operations',
        slug: 'operations',
        name: 'Operations',
        description: 'Operations and Employee management',
        icon: 'mdi:account-tie',
        color: '#10B981',
        modules: operationsModules,
        enabled: true
    },
    {
        id: 'prog-crewbuilder',
        name: 'Crew Builder',
        slug: 'crewbuilder',
        description: 'Design and manage AI agent crews',
        icon: 'mdi:account-group',
        color: '#8B5CF6',
        modules: [
            {
                id: 'mod-cb-main',
                name: 'Crew Builder',
                slug: 'builder',
                submodules: [
                    {
                        id: 'sub-cb-dashboard',
                        name: 'Dashboard',
                        slug: 'dashboard',
                        type: 'module',
                        icon: 'mdi:view-dashboard'
                    }
                ]
            }
        ],
        enabled: true
    }
];

// Sample Clients
export const mockClients: Client[] = [
    {
        id: 'client-epson',
        slug: 'epson',
        name: 'Epson',
        logo: '/logos/epson.svg',
        theme: 'corporate',
        primaryColor: '#003399',
        ssoProviders: [
            {
                provider: 'basic',
                enabled: true,
                label: 'Sign in with Email'
            },
            {
                provider: 'microsoft',
                enabled: true,
                clientId: 'mock-client-id',
                tenantId: 'mock-tenant-id',
                label: 'Sign in with Microsoft'
            }
        ],
        programs: epsonPrograms,
        groups: ['admin', 'managers', 'users']
    },
    {
        id: 'client-trocdigital',
        slug: 'trocdigital',
        name: 'TrocDigital',
        logo: '/logos/trocdigital.svg',
        theme: 'night',
        primaryColor: '#6366F1',
        ssoProviders: [
            {
                provider: 'basic',
                enabled: true,
                label: 'Sign in'
            }
        ],
        programs: [
            {
                id: 'prog-navigator',
                slug: 'navigator',
                name: 'Navigator',
                description: 'Data Navigator platform',
                icon: 'mdi:compass',
                color: '#6366F1',
                modules: [],
                enabled: true
            }
        ],
        groups: ['admin', 'developers']
    }
];

// Default client for localhost development
export const defaultClient: Client = {
    id: 'client-default',
    slug: 'localhost',
    name: config.appName,
    logo: undefined,
    theme: 'dark',
    primaryColor: '#6366F1',
    ssoProviders: [
        {
            provider: 'basic',
            enabled: true,
            label: 'Sign in'
        }
    ],
    programs: epsonPrograms, // Use Epson programs for demo
    groups: ['admin']
};

/**
 * Get client by slug (subdomain)
 */
export function getClientBySlug(slug: string): Client | undefined {
    if (slug === 'localhost' || slug === '127.0.0.1' || !slug) {
        return defaultClient;
    }
    return mockClients.find((c) => c.slug === slug);
}

/**
 * Get program by slug within a client
 */
export function getProgramBySlug(client: Client, programSlug: string): Program | undefined {
    return client.programs.find((p) => p.slug === programSlug);
}

/**
 * Get module by slug within a program
 */
export function getModuleBySlug(program: Program, moduleSlug: string): Module | undefined {
    return program.modules.find((m) => m.slug === moduleSlug);
}

/**
 * Get submodule by slug within a module
 */
export function getSubmoduleBySlug(module: Module, submoduleSlug: string): Submodule | undefined {
    return module.submodules.find((s) => s.slug === submoduleSlug);
}
