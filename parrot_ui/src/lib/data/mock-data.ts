// src/lib/data/mock-data.ts

/**
 * Mock Data for Development
 * Simulates API responses for clients, programs, modules, and submodules
 */

import type { Client, Program, Module, Submodule } from '$lib/types';

// Sample Submodules
const retailSalesSubmodules: Submodule[] = [
    {
        id: 'sub-retail-pos',
        slug: 'pos',
        name: 'Point of Sale',
        description: 'POS terminal management',
        icon: 'mdi:cash-register',
        type: 'container',
        order: 1
    },
    {
        id: 'sub-retail-orders',
        slug: 'orders',
        name: 'Orders',
        description: 'Order management and tracking',
        icon: 'mdi:clipboard-list',
        type: 'container',
        order: 2
    },
    {
        id: 'sub-retail-returns',
        slug: 'returns',
        name: 'Returns & Refunds',
        description: 'Process returns and refunds',
        icon: 'mdi:keyboard-return',
        type: 'module',
        order: 3
    }
];

const inventorySubmodules: Submodule[] = [
    {
        id: 'sub-inv-stock',
        slug: 'stock',
        name: 'Stock Levels',
        description: 'Monitor inventory levels',
        icon: 'mdi:package-variant',
        type: 'container',
        order: 1
    },
    {
        id: 'sub-inv-warehouse',
        slug: 'warehouse',
        name: 'Warehouse',
        description: 'Warehouse management',
        icon: 'mdi:warehouse',
        type: 'container',
        order: 2
    },
    {
        id: 'sub-inv-receiving',
        slug: 'receiving',
        name: 'Receiving',
        description: 'Inbound shipments',
        icon: 'mdi:truck-delivery',
        type: 'module',
        order: 3
    }
];

const reportsSubmodules: Submodule[] = [
    {
        id: 'sub-rep-sales',
        slug: 'sales-reports',
        name: 'Sales Reports',
        description: 'Sales analytics and reports',
        icon: 'mdi:chart-line',
        type: 'container',
        order: 1
    },
    {
        id: 'sub-rep-inventory',
        slug: 'inventory-reports',
        name: 'Inventory Reports',
        description: 'Stock and movement reports',
        icon: 'mdi:chart-bar',
        type: 'container',
        order: 2
    }
];

// Sample Modules
const epsonModules: Module[] = [
    {
        id: 'mod-sales',
        slug: 'sales',
        name: 'Sales',
        description: 'Sales management and operations',
        icon: 'mdi:cart',
        submodules: retailSalesSubmodules,
        order: 1
    },
    {
        id: 'mod-inventory',
        slug: 'inventory',
        name: 'Inventory',
        description: 'Inventory and stock management',
        icon: 'mdi:package-variant-closed',
        submodules: inventorySubmodules,
        order: 2
    },
    {
        id: 'mod-reports',
        slug: 'reports',
        name: 'Reports',
        description: 'Analytics and reporting',
        icon: 'mdi:chart-areaspline',
        submodules: reportsSubmodules,
        order: 3
    }
];

const hrModules: Module[] = [
    {
        id: 'mod-employees',
        slug: 'employees',
        name: 'Employees',
        description: 'Employee management',
        icon: 'mdi:account-group',
        submodules: [
            {
                id: 'sub-emp-directory',
                slug: 'directory',
                name: 'Directory',
                description: 'Employee directory',
                icon: 'mdi:account-search',
                type: 'container',
                order: 1
            },
            {
                id: 'sub-emp-onboarding',
                slug: 'onboarding',
                name: 'Onboarding',
                description: 'New employee onboarding',
                icon: 'mdi:account-plus',
                type: 'module',
                order: 2
            },
            {
                id: 'sub-emp-hr-chat',
                slug: 'hr-chat',
                name: 'HR Chat',
                description: 'Chat with the HR assistant',
                icon: 'mdi:robot-outline',
                type: 'component',
                path: 'agents/AgentChat.svelte',
                parameters: {
                    agent_name: 'hr_agent'
                },
                order: 3
            }
        ],
        order: 1
    },
    {
        id: 'mod-attendance',
        slug: 'attendance',
        name: 'Attendance',
        description: 'Time and attendance tracking',
        icon: 'mdi:clock-check',
        submodules: [
            {
                id: 'sub-att-timesheets',
                slug: 'timesheets',
                name: 'Timesheets',
                description: 'Employee timesheets',
                icon: 'mdi:calendar-clock',
                type: 'container',
                order: 1
            }
        ],
        order: 2
    }
];

// Sample Programs
const epsonPrograms: Program[] = [
    {
        id: 'prog-retail',
        slug: 'retail',
        name: 'Retail Operations',
        description: 'Manage retail stores, sales, and inventory',
        icon: 'mdi:store',
        color: '#3B82F6',
        modules: epsonModules,
        enabled: true
    },
    {
        id: 'prog-hr',
        slug: 'hr',
        name: 'Human Resources',
        description: 'Employee management and HR operations',
        icon: 'mdi:account-tie',
        color: '#10B981',
        modules: hrModules,
        enabled: true
    },
    {
        id: 'prog-finance',
        slug: 'finance',
        name: 'Finance',
        description: 'Financial management and accounting',
        icon: 'mdi:currency-usd',
        color: '#F59E0B',
        modules: [],
        enabled: true
    },
    {
        id: 'prog-analytics',
        slug: 'analytics',
        name: 'Business Analytics',
        description: 'Advanced analytics and insights',
        icon: 'mdi:chart-bubble',
        color: '#8B5CF6',
        modules: [],
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
    name: 'AI Parrot',
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
