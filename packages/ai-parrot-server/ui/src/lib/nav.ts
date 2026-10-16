/**
 * Sidebar navigation registry (TASK-2528).
 *
 * Data-only module — no components — so future module specs (agent
 * management, crews, etc.) append entries here without touching
 * `AppShell.svelte`/`Sidebar.svelte`. `icon` is a small inline SVG path
 * string (no icon library dependency was vendored by TASK-2525).
 *
 * `section` groups entries in the sidebar: "user" pages are the end-user
 * surface served at the site root, "admin" pages live under `/admin`.
 */

export type NavSection = "user" | "admin";

export interface NavEntry {
  /** Absolute in-app path (matches a `RouteDefinition.path`). */
  path: string;
  label: string;
  /** SVG `<path d="...">` data for a 24x24 viewBox stroke icon. */
  icon: string;
  section: NavSection;
}

export const navSections: { id: NavSection; label: string }[] = [
  { id: "user", label: "Workspace" },
  { id: "admin", label: "Admin" },
];

export const navEntries: NavEntry[] = [
  {
    path: "/agents",
    label: "Agents",
    icon: "M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z",
    section: "user",
  },
  {
    path: "/admin/home",
    label: "Home",
    icon: "M3 12l9-9 9 9M5 10v10a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V10",
    section: "admin",
  },
  {
    path: "/admin/dashboard",
    label: "Dashboard",
    icon: "M4 4h6v6H4V4zm10 0h6v6h-6V4zM4 14h6v6H4v-6zm10 0h6v6h-6v-6z",
    section: "admin",
  },
  {
    path: "/admin/agents",
    label: "Manage agents",
    icon: "M12 4a4 4 0 100 8 4 4 0 000-8zM4 20c0-3.3 3.6-6 8-6s8 2.7 8 6",
    section: "admin",
  },
];
