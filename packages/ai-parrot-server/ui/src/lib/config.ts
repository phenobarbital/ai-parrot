/**
 * Admin UI runtime configuration.
 *
 * Adapted from navigator-frontend-next's `src/lib/config.ts` (TASK-2527)
 * for a plain Vite SPA: the only SvelteKit coupling in the source
 * (the SvelteKit dynamic public env module) is replaced with `import.meta.env`. Trimmed to
 * only the fields the Admin UI's own runtime (router/auth/API client)
 * needs — no querysource/avatar/agent-specific fields.
 */

// Same-origin by default (empty axios baseURL -> relative request URLs like
// "/api/v1/login" resolve against whatever origin the SPA itself was loaded
// from). This MUST stay relative in production: setup_admin_ui() serves the
// SPA from the same aiohttp app that serves /api/*, at whatever host/port/
// scheme/reverse-proxy path the deployment actually uses — a hardcoded
// absolute default here would get baked into the production bundle at
// `pnpm build` time (no PUBLIC_API_URL is set in Makefile's
// build-server-ui target or .github/workflows/release.yml's build-server
// job) and every API call, including login, would go to the wrong origin
// on any host other than a bare "http://localhost:5000". `pnpm dev` does
// NOT need an absolute value here either — vite.config.ts's own dev-server
// proxy independently forwards relative `/api/*` requests to a real
// backend (defaulting to http://localhost:5000, overridable via the same
// PUBLIC_API_URL) regardless of what this module resolves to.
const DEFAULT_API = "";

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
  authMethodsUrl: "/api/v1/auth/methods",
  /** localStorage key for the bearer token — MUST match
   * parrot_formdesigner's templates.py and parrot/autonomous/admin.py's
   * inline admin page (Codebase Contract, TASK-2527). */
  tokenStorageKey: "ai_parrot_token",
  /** localStorage key for the raw login response payload (user info). */
  sessionStorageKey: "ai_parrot_session",
  /** FEAT-476: base path AgentChat's vendored `api/agent.ts` /
   * `api/stream.ts` POST to (`AgentTalk`, `manager.py:1991-1992`). */
  agentsChatPath: "/api/v1/agents/chat",
  /** FEAT-476: voice turn upload (`AgentVoiceTalk`, `manager.py:1772`,
   * registered only when `ai-parrot-integrations[voice]` imports). */
  agentsVoicePath: "/api/v1/agents/voice",
  /** FEAT-476: avatar viewer/session routes (`handlers/avatar.py:681,686`,
   * `handlers/avatar_fullmode.py:484-494`). */
  agentsAvatarPath: "/api/v1/agents/avatar",
  /** FEAT-476: conversation history sync (`ChatInteractionHandler`,
   * `manager.py:2212-2213`). */
  chatInteractionsPath: "/api/v1/chat/interactions",
  /** FEAT-476 (TASK-2592): Dexie database name prefix for
   * `services/chat-db.ts`'s local conversation store — navigator derives
   * this from its multi-tenant `storageNamespace`; the Admin UI has no
   * tenant concept, so it is a fixed, namespaced constant instead. */
  conversationStoragePrefix: "ai_parrot_agentchat",
};
