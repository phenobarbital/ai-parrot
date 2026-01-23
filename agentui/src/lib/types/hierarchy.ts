// src/lib/types/hierarchy.ts

/**
 * Hierarchy Types for AgentUI Multi-Tenant Structure
 *
 * Client (subdomain/domain)
 * ├── Config SSO/Auth per-client
 * ├── Groups (client-groups)
 * └── Programs (tenants)
 *     └── Modules (services)
 *         └── Submodules (sub-division)
 *             ├── Dashboard-container (tabs → widgets)
 *             └── Dashboard-module (full-screen components)
 */

// SSO Provider Configuration
export interface SSOConfig {
    provider: 'basic' | 'google' | 'microsoft' | 'okta' | 'saml';
    enabled: boolean;
    clientId?: string;
    tenantId?: string;
    label?: string;
    icon?: string;
}

// Dashboard Configuration for Submodules
export interface DashboardConfig {
    id?: string;
    tabs?: DashboardTab[];
    component?: string; // For dashboard-module type
    props?: Record<string, unknown>;
}

export interface DashboardTab {
    id: string;
    name: string;
    widgets: WidgetConfig[];
}

export interface WidgetConfig {
    id: string;
    type: string;
    title: string;
    position: { x: number; y: number; w: number; h: number };
    config?: Record<string, unknown>;
}

// Submodule - subdivision of modules
export interface Submodule {
    id: string;
    slug: string;
    name: string;
    description?: string;
    icon?: string;
    type: 'container' | 'module' | 'component'; // tabs vs full-screen
    dashboardConfig?: DashboardConfig;
    path?: string;
    parameters?: Record<string, unknown>;
    order?: number;
}

// Module - services of each tenant (e.g., "sales", "inventory")
export interface Module {
    id: string;
    slug: string;
    name: string;
    description?: string;
    icon?: string;
    submodules: Submodule[];
    order?: number;
}

// Program - tenant organization within a client
export interface Program {
    id: string;
    slug: string;
    name: string;
    description?: string;
    icon?: string;
    color?: string; // Primary accent color
    modules: Module[];
    enabled?: boolean;
}

// Client - top-level organization (by subdomain/domain)
export interface Client {
    id: string;
    slug: string; // subdomain identifier
    name: string;
    logo?: string;
    favicon?: string;
    theme?: string; // DaisyUI theme name
    primaryColor?: string;
    ssoProviders: SSOConfig[];
    programs: Program[];
    groups?: string[];
}

// Navigation State
export interface NavigationContext {
    client: Client | null;
    program: Program | null;
    module: Module | null;
    submodule: Submodule | null;
}

// Breadcrumb Item
export interface BreadcrumbItem {
    label: string;
    href: string;
    icon?: string;
}
