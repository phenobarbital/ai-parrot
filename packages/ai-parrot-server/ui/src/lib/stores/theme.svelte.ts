/**
 * ThemeStore (TASK-2527), adapted from navigator-frontend-next's
 * `src/lib/stores/theme.svelte.ts`.
 *
 * Deviations from the source (Codebase Contract: "strip its cookie/SSR
 * sync — SPA is client-only"):
 *  - No cookie read/write — the source's cookie was only there to keep an
 *    SSR-rendered `<html data-theme>` in sync with the client; this SPA
 *    has no SSR, so `localStorage` alone is the source of truth.
 *  - Only "light"/"dark" theme names — TASK-2525 vendored only those two
 *    theme CSS files (midnight/warm were explicitly optional and are not
 *    present in this scaffold).
 *  - No SvelteKit environment guard — always running in the browser.
 */

export const THEME_NAMES = ["light", "dark"] as const;
export type ThemeName = (typeof THEME_NAMES)[number];
export const DEFAULT_THEME: ThemeName = "light";

export function isThemeName(value: unknown): value is ThemeName {
  return typeof value === "string" && (THEME_NAMES as readonly string[]).includes(value);
}

const STORAGE_KEY = "ai_parrot_theme";

class ThemeStore {
  currentTheme = $state<ThemeName>(DEFAULT_THEME);
  isDark = $derived(this.currentTheme === "dark");

  /** Read the persisted theme (if any) and apply it to the DOM. */
  init() {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch {
      // localStorage unavailable (private mode) — fall back to default.
    }
    const next = isThemeName(stored) ? stored : DEFAULT_THEME;
    this.currentTheme = next;
    this.applyTheme(next);
  }

  /** Set the active theme. @param persist Whether to write to localStorage (default true). */
  setTheme(theme: ThemeName, persist = true) {
    if (!isThemeName(theme)) return;
    this.currentTheme = theme;
    if (persist) this.persist(theme);
    this.applyTheme(theme);
  }

  toggleDarkMode() {
    const next: ThemeName = this.currentTheme === "dark" ? "light" : "dark";
    this.setTheme(next, true);
  }

  private persist(theme: ThemeName) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // localStorage unavailable — theme still applies for this session.
    }
  }

  private applyTheme(theme: ThemeName) {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    root.classList.toggle("dark", theme === "dark");
  }
}

export { ThemeStore };

export const themeStore = new ThemeStore();
