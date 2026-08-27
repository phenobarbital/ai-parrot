/**
 * Hand-rolled history-mode router (TASK-2527).
 *
 * No router library (svelte-spa-router / tinro) is used per the resolved
 * design decision — this is intentionally small (~100 lines) rather than a
 * general-purpose router. Base-path aware (`config.basePath`, `/admin`):
 * every path this class deals with is an absolute in-app path starting
 * with `/admin` (matching `window.location.pathname` when the SPA is
 * served at that prefix).
 *
 * `guard()` reads the auth token directly from localStorage (via
 * `config.tokenStorageKey`) rather than importing `AuthStore`, so this
 * module has zero dependency on `stores/auth.svelte.ts` — that keeps the
 * router -> auth -> http -> router path from ever forming a cycle.
 */
import { config } from "./config";

export type RouteComponentLoader = () => Promise<{ default: unknown }>;

export interface RouteDefinition {
  /** Absolute in-app path, e.g. "/admin/login". */
  path: string;
  /** Lazy import of the page component for this route (code-splitting). */
  component: RouteComponentLoader;
  /** When true, `guard()` redirects unauthenticated visitors to login. */
  requiresAuth?: boolean;
}

function isInAppPath(path: string): boolean {
  return typeof path === "string" && path.startsWith(config.basePath);
}

function hasToken(): boolean {
  try {
    return Boolean(localStorage.getItem(config.tokenStorageKey));
  } catch {
    // localStorage unavailable (private mode / SSR) — treat as unauthenticated.
    return false;
  }
}

class Router {
  path = $state(
    typeof window !== "undefined" ? window.location.pathname : config.basePath,
  );

  routes: RouteDefinition[] = [];

  constructor(routes: RouteDefinition[] = []) {
    this.routes = routes;
    if (typeof window !== "undefined") {
      window.addEventListener("popstate", () => {
        this.path = window.location.pathname;
      });
    }
  }

  /** Navigate to an in-app path, pushing a new history entry. */
  navigate(to: string, { replace = false }: { replace?: boolean } = {}): void {
    if (typeof window === "undefined") {
      this.path = to;
      return;
    }
    if (replace) {
      window.history.replaceState({}, "", to);
    } else {
      window.history.pushState({}, "", to);
    }
    this.path = to;
  }

  /** Find the route definition matching the current `path` (exact match). */
  match(path: string = this.path): RouteDefinition | undefined {
    return this.routes.find((r) => r.path === path);
  }

  /**
   * Enforce auth for the current path: if it requires auth and there is no
   * stored token, redirect to the login route with `?next=<intended>` and
   * return false. Returns true when navigation may proceed as-is.
   */
  guard(path: string = this.path): boolean {
    const route = this.match(path);
    if (!route?.requiresAuth) return true;
    if (hasToken()) return true;

    const next = isInAppPath(path) ? path : config.basePath;
    this.navigate(
      `${config.loginPath}?next=${encodeURIComponent(next)}`,
      { replace: true },
    );
    return false;
  }
}

export { Router, isInAppPath };

export const router = new Router();
