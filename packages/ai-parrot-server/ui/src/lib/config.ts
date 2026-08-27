/**
 * Admin UI runtime configuration.
 *
 * Adapted from navigator-frontend-next's `src/lib/config.ts` (TASK-2527)
 * for a plain Vite SPA: the only SvelteKit coupling in the source
 * (the SvelteKit dynamic public env module) is replaced with `import.meta.env`. Trimmed to
 * only the fields the Admin UI's own runtime (router/auth/API client)
 * needs — no querysource/avatar/agent-specific fields.
 */

const DEFAULT_API = "http://localhost:5000";

const parseEnvBoolean = (
  value: string | boolean | undefined,
  defaultValue = false,
): boolean => {
  if (value === undefined || value === null) return defaultValue;
  if (typeof value === "boolean") return value;
  return value.toLowerCase() === "true" || value === "1";
};

const env = import.meta.env;

const rawBaseUrl = env.PUBLIC_API_URL ?? DEFAULT_API;
const apiBaseUrl = rawBaseUrl.replace(/\/$/, "");
const apiWithCredentials = parseEnvBoolean(env.PUBLIC_API_WITH_CREDENTIALS, false);

/** Base path the Admin UI SPA is mounted under (see vite.config.ts `base`). */
const basePath = "/admin";

export const config = {
  apiBaseUrl,
  apiWithCredentials,
  basePath,
  loginPath: `${basePath}/login`,
  loginUrl: "/api/v1/login",
  logoutUrl: "/api/v1/logout",
  /** localStorage key for the bearer token — MUST match
   * parrot_formdesigner's templates.py and parrot/autonomous/admin.py's
   * inline admin page (Codebase Contract, TASK-2527). */
  tokenStorageKey: "ai_parrot_token",
  /** localStorage key for the raw login response payload (user info). */
  sessionStorageKey: "ai_parrot_session",
};
