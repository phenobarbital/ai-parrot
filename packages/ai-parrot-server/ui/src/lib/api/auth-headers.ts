/**
 * Shared auth header utility for browser-based (non-Axios) API calls, e.g.
 * `fetch`-based WebSocket upgrade requests.
 *
 * Adapted from navigator-frontend-next's `src/lib/api/auth-headers.ts`
 * (TASK-2527): the SvelteKit environment browser guard is dropped (this SPA
 * has no SSR) and the token is read as a raw string — `config.tokenStorageKey`
 * stores the bearer token directly, not a JSON blob (see `http.ts`).
 */
import { config } from "$lib/config";

/**
 * Read the auth token from localStorage and return an Authorization header.
 * Returns an empty object if no token is stored.
 */
export function getAuthHeaders(): Record<string, string> {
  try {
    const token = localStorage.getItem(config.tokenStorageKey);
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
  } catch {
    return {};
  }
}
