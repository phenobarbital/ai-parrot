/**
 * Shim for SvelteKit's `$env/dynamic/public` module.
 *
 * Resolved via `vite.config.ts`'s `resolve.alias` (FEAT-476 spec §2
 * "Shims") so the vendored navigator tree's `import { env } from
 * "$env/dynamic/public"` sites (e.g. navigator's `config.ts:1`) keep
 * working verbatim. SvelteKit's dynamic public env is a runtime-read
 * object of `PUBLIC_*` variables; in this plain Vite SPA the equivalent
 * is `import.meta.env`, which already exposes `PUBLIC_*` (and `VITE_*`)
 * via `vite.config.ts`'s `envPrefix`.
 */
export const env: Record<string, string | undefined> = import.meta.env;
