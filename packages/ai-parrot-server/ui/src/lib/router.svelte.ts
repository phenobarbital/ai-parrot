/**
 * Hand-rolled history-mode router (TASK-2527; `:param` segments + the
 * `beforeNavigate` hook added in TASK-2585, FEAT-475).
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
  /** Absolute in-app path, e.g. "/admin/login" or "/admin/agents/:name". */
  path: string;
  /** Lazy import of the page component for this route (code-splitting). */
  component: RouteComponentLoader;
  /** When true, `guard()` redirects unauthenticated visitors to login. */
  requiresAuth?: boolean;
}

/**
 * Split a path into non-empty segments (ignores a query string and any
 * leading/trailing slashes), e.g. "/admin/agents/helpdesk" ->
 * ["admin", "agents", "helpdesk"].
 */
function segments(path: string): string[] {
  return path.split("?")[0].split("/").filter(Boolean);
}

/**
 * Match a single route definition's path against a pathname's segments,
 * returning the captured `:param` values on success or `null` otherwise.
 * Segment counts must match exactly (no partial/prefix matching).
 */
function matchRoute(
  routePath: string,
  pathSegments: string[],
): Record<string, string> | null {
  const routeSegments = segments(routePath);
  if (routeSegments.length !== pathSegments.length) return null;

  const params: Record<string, string> = {};
  for (let i = 0; i < routeSegments.length; i++) {
    const routeSeg = routeSegments[i];
    const pathSeg = pathSegments[i];
    if (routeSeg.startsWith(":")) {
      params[routeSeg.slice(1)] = decodeURIComponent(pathSeg);
    } else if (routeSeg !== pathSeg) {
      return null;
    }
  }
  return params;
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

  /**
   * Captured `:param` values from the route matched against the current
   * `path` (populated by `match()`). Empty object when the matched route
   * has no param segments, or nothing matched.
   */
  params = $state<Record<string, string>>({});

  routes: RouteDefinition[] = [];

  /**
   * Optional in-app navigation guard consulted by `navigate()` before the
   * history entry is pushed. Returning (or resolving to) `false` cancels
   * the navigation — `this.path`/history are left untouched. Sync or
   * async: `navigate()` stays a synchronous void method (App.svelte's
   * `resolve()` and every existing caller depend on that), so an async
   * hook's push is deferred until its promise resolves rather than making
   * `navigate()` itself async.
   *
   * `guard()`'s own login redirect always bypasses this hook (see
   * `guard()`) — an unsaved-changes prompt must never block the forced
   * redirect to login on a 401/missing token.
   */
  beforeNavigate: ((to: string) => boolean | Promise<boolean>) | null = null;

  constructor(routes: RouteDefinition[] = []) {
    this.routes = routes;
    if (typeof window !== "undefined") {
      window.addEventListener("popstate", () => {
        this.path = window.location.pathname;
      });
    }
  }

  /** Push `to` onto history and update `this.path` — the actual navigation,
   * bypassing `beforeNavigate` (used internally once the hook has already
   * allowed the navigation, and by `guard()`'s forced login redirect). */
  private _commit(to: string, { replace = false }: { replace?: boolean } = {}): void {
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

  /**
   * Navigate to an in-app path, pushing a new history entry.
   *
   * When `beforeNavigate` is set, it is consulted first; a `false` (or
   * promise resolving to `false`) return cancels the navigation. The hook
   * result may be a promise — in that case the push is deferred until it
   * settles, but `navigate()` itself still returns synchronously (fire and
   * forget), preserving the existing sync call sites.
   */
  navigate(to: string, options: { replace?: boolean } = {}): void {
    if (!this.beforeNavigate) {
      this._commit(to, options);
      return;
    }
    const result = this.beforeNavigate(to);
    if (typeof result === "boolean") {
      if (result) this._commit(to, options);
      return;
    }
    // Promise: defer the commit until it resolves; a rejection is treated
    // as "cancel" (never lets a hook error silently navigate anyway).
    result
      .then((allowed) => {
        if (allowed) this._commit(to, options);
      })
      .catch(() => {
        /* cancel on rejection */
      });
  }

  /**
   * Find the route definition matching the current `path`. Supports
   * `:param` segments (e.g. "/admin/agents/:name" matches
   * "/admin/agents/helpdesk", populating `this.params.name`); a static
   * route always wins over a param route when both match the same
   * pathname. A query string, e.g. the login route's own
   * `?next=<encoded>` produced by `guard()`/`AuthStore.handle401()`, is
   * stripped before comparing. Without this, `router.path` values like
   * `/admin/login?next=%2Fadmin%2Fdashboard` would never match the route
   * table's bare `/admin/login` entry, and `App.svelte`'s `resolve()`
   * would treat the login redirect as an unmatched route and immediately
   * navigate away again — wiping `?next=` before `Login.svelte` ever
   * mounts to read it.
   */
  match(path: string = this.path): RouteDefinition | undefined {
    const pathname = path.split("?")[0];
    const pathSegments = segments(pathname);

    // Static routes first (no ":" segment) so e.g. "/admin/agents/new"
    // always wins over "/admin/agents/:name".
    const staticRoutes = this.routes.filter((r) => !r.path.includes(":"));
    const paramRoutes = this.routes.filter((r) => r.path.includes(":"));

    for (const route of staticRoutes) {
      if (matchRoute(route.path, pathSegments)) {
        this.params = {};
        return route;
      }
    }
    for (const route of paramRoutes) {
      const params = matchRoute(route.path, pathSegments);
      if (params) {
        this.params = params;
        return route;
      }
    }
    return undefined;
  }

  /**
   * Enforce auth for the current path: if it requires auth and there is no
   * stored token, redirect to the login route with `?next=<intended>` and
   * return false. Returns true when navigation may proceed as-is.
   *
   * Bypasses `beforeNavigate` deliberately (commits directly) — an
   * unsaved-changes guard must never block the forced redirect to login.
   */
  guard(path: string = this.path): boolean {
    const route = this.match(path);
    if (!route?.requiresAuth) return true;
    if (hasToken()) return true;

    const next = isInAppPath(path) ? path : config.basePath;
    this._commit(
      `${config.loginPath}?next=${encodeURIComponent(next)}`,
      { replace: true },
    );
    return false;
  }
}

export { Router, isInAppPath };

export const router = new Router();
