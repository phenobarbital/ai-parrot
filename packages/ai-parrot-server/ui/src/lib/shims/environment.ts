/**
 * Shim for SvelteKit's `$app/environment` module.
 *
 * The Admin UI is a plain Vite SPA (TASK-2525), not SvelteKit — this
 * module is resolved via `vite.config.ts`'s `resolve.alias` so the
 * vendored navigator tree's `import { browser } from "$app/environment"`
 * sites (FEAT-476 spec §2 "Shims") keep working verbatim. There is no
 * server-rendering path in this SPA, so `browser` is always `true`.
 *
 * ai-parrot: navigator's `$app/environment` also exports `dev`/`building`;
 * only `browser` is used by the vendored AgentChat closure, so only it is
 * shimmed here.
 */
export const browser = true;
