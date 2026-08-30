/**
 * Build-time AgentChat feature flags (FEAT-476 spec §2 "Feature flags").
 *
 * Backed by the `__AGENTCHAT_*__` compile-time constants `vite.config.ts`
 * injects via `define` (from the `PUBLIC_AGENTCHAT_*` env vars, default
 * `true`). Every gated component/import is reached only through
 * `if (features.x) await import(...)`, and the markup that triggers it is
 * wrapped in `{#if features.x}` — this hides the related UI and, at
 * runtime, means the guarded chunk is never *fetched* when a flag is
 * `false`.
 *
 * KNOWN LIMITATION (see `docs/admin-ui.md` "Known limitation"): because
 * `features.x` is a runtime object-property read (not a bare `const` at
 * each call site), Rollup's dead-code elimination cannot prove the
 * guarded `import()` is unreachable when the flag is compiled `false` —
 * the chunk is still *emitted* into `dist/assets` (verified: CHARTS/
 * MAPS/AVATAR/RICH_EDITOR builds are byte-for-byte identical on/off). A
 * real per-flag chunk-removal fix would require flattening this module
 * to individual `const` exports, a cross-cutting change deferred as a
 * follow-up (tracked in TASK-2598's Completion Note).
 */
export const features = Object.freeze({
  voice: __AGENTCHAT_VOICE__,
  avatar: __AGENTCHAT_AVATAR__,
  maps: __AGENTCHAT_MAPS__,
  charts: __AGENTCHAT_CHARTS__,
  canvas: __AGENTCHAT_CANVAS__,
  infographic: __AGENTCHAT_INFOGRAPHIC__,
  datasets: __AGENTCHAT_DATASETS__,
  richEditor: __AGENTCHAT_RICH_EDITOR__,
});
