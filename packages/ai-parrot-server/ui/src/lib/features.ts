/**
 * Build-time AgentChat feature flags (FEAT-476 spec §2 "Feature flags").
 *
 * Backed by the `__AGENTCHAT_*__` compile-time constants `vite.config.ts`
 * injects via `define` (from the `PUBLIC_AGENTCHAT_*` env vars, default
 * `true`). Every gated component/import is reached only through
 * `if (features.x) await import(...)`, and the markup that triggers it is
 * wrapped in `{#if features.x}`, so Rollup drops the corresponding chunk
 * when a flag is compiled `false`.
 *
 * `features` is a frozen object of plain booleans (no getters) so
 * `{#if features.x}` stays statically analysable by Svelte/Rollup's
 * dead-code elimination.
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
