---
id: F016
query_id: Q054
type: git_log
intent: "Recent history: registry (remote agents)."
executed_at: 2026-10-25T22:41:57Z
duration_ms: 350
parent_id: null
depth: 0
lane_origin: FG-004-registry-history
---

# F016 — AgentRegistry history: YAML-backed agent definitions, tooling updates; no remote-agent/kind commits

## Summary

15 commits in 180 days on `parrot/registry/`. Themes: AgentStudio management (registry primitives + lossless YAML round-trip, TASK-2509, 08-27), tool-configuration-agentstudio (`AgentRegistry.update_agent_tooling()` atomic YAML rewrite, normalize factory, 09-23), a public agent enumerator + tool catalog fix (08-17), error-cause preservation (08-11), StoreRouter decoupling (07-27), intent-router config (06-05), CodeQL fixes (08-20). No commit message mentions remote agents, A2A kind, endpoints or protocol discovery — so D10's claim "AgentRegistry already registers remote agents and their kind" is not visible in registry history (it may live in the A2A mesh/router instead; see FG-001).

## Citations

- path: `packages/ai-parrot/src/parrot/registry/`
  commit: `f638ba6fad` 2026-09-23 Jesus — feat(tool-configuration-agentstudio): TASK-3657 — AgentRegistry.update_agent_tooling() in-place atomic YAML rewrite
- path: `packages/ai-parrot/src/parrot/registry/`
  commit: `5a75a8fbab` 2026-09-23 Jesus — feat(tool-configuration-agentstudio): TASK-3656 — registry normalize factory
- path: `packages/ai-parrot/src/parrot/registry/`
  commit: `6571889ebb` 2026-08-27 Jesus Lara — feat(agentstudio-management): TASK-2509 — Registry primitives + lossless YAML round-trip
- path: `packages/ai-parrot/src/parrot/registry/`
  commit: `b9735c6f59` 2026-08-17 Claude — feat(registry): add a public agent enumerator; fix the tool catalog
- path: `packages/ai-parrot/src/parrot/registry/`
  commit: `9e867b855f` 2026-08-11 Javier León — fix(registry): stop discarding the cause of agent instantiation failures
- path: `packages/ai-parrot/src/parrot/registry/`
  commit: `cb81523d7b` 2026-07-27 Jesus — feat(multistoresearchtool-parrotwiki): TASK-1931 — StoreRouter & AbstractBot decoupling via MultiSearch protocol

## Notes

[cross-lane: type=grep, intent=verify in registry source whether any remote/A2A agent kind or endpoint field exists (D10); if absent, check parrot/a2a mesh/router]
