---
id: FG-001
query_id: Q050
type: git_log
intent: "Recent activity on the registry (is it being extended right now; FEAT ids touching it)."
executed_at: 2026-10-25T22:41:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-001 — AgentRegistry history (180 days): PBAC enforcement, AgentStudio YAML round-trip, a `capabilities/` + `routing/` sub-package

## Summary

22 commits since 2026-04-28, all by Jesus Lara / Claude / Javier León. Dominant themes: (1) PBAC enforcement in `AgentRegistry.get_instance` and DB-backed bot policies (FEAT-153, May 2026); (2) AgentStudio management — registry primitives, lossless YAML round-trip, `update_agent_tooling()` atomic rewrite, "normalize factory" (TASK-2509/3656/3657, Aug–Sep 2026); (3) a public agent enumerator and tool catalog fix (Aug 17). The log also reveals two sub-packages the brainstorm does not mention: `registry/capabilities/models.py` (IntentRouterConfig, June 2026) and `registry/routing/` (EmbeddingIntentRouter, StoreRouter, cache, rules). So "capabilities" already exists as a name in the registry — but for intent-routing config, not a capability directory. Last change 2026-09-23; the module is stable, not under active edit.

## Citations

- sha: `0c4f5ebb5d` date: 2026-05-07 author: Jesus Lara — feat(botmanager-pbac-permissions): TASK-1054 — AgentRegistry.get_instance enforcement — files: `packages/ai-parrot/src/parrot/registry/registry.py`
- sha: `fc304d5267` date: 2026-05-07 author: Jesus Lara — feat(botmanager-pbac-permissions): TASK-1051 — AgentRegistry.register_db_bot_policies — files: `registry/registry.py`
- sha: `546c277917` date: 2026-05-15 author: Jesus Lara — feat(lifecycle-events-system): TASK-1196 — BotManager YAML events loader — files: `registry/registry.py`
- sha: `04cd4a47bd` date: 2026-06-05 author: Jesus Lara — feat(intent-router): TASK-1485 — extend IntentRouterConfig with output-mode fields — files: `registry/capabilities/models.py`
- sha: `9b9c16db7d` date: 2026-06-05 author: Jesus Lara — feat(intent-router): TASK-1484 — EmbeddingIntentRouter engine — files: `registry/routing/embedding_router.py`
- sha: `cb81523d7b` date: 2026-07-27 author: Jesus — TASK-1931 — StoreRouter & AbstractBot decoupling via MultiSearch protocol — files: `registry/routing/store_router.py`
- sha: `b9735c6f59` date: 2026-08-17 author: Claude — feat(registry): add a public agent enumerator; fix the tool catalog — files: `registry/registry.py`
- sha: `6571889ebb` date: 2026-08-27 author: Jesus Lara — feat(agentstudio-management): TASK-2509 — Registry primitives + lossless YAML round-trip — files: `registry/registry.py`
- sha: `f638ba6fad` date: 2026-09-23 author: Jesus — TASK-3657 — AgentRegistry.update_agent_tooling() in-place atomic YAML rewrite — files: `registry/registry.py`
- sha: `2c65632c39` date: 2026-09-23 author: Jesus — fix: resolve pre-existing F841/F811 in registry.py — files: `registry/registry.py`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `AgentRegistry`
  excerpt: |
    (file identified by all registry commits; holds get_instance PBAC enforcement,
     register_db_bot_policies, update_agent_tooling, public agent enumerator)
- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  symbol: `IntentRouterConfig`
  excerpt: |
    (identified by 04cd4a47bd; "capabilities" here = intent-router config, not a capability directory)
- path: `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py`
  symbol: `EmbeddingIntentRouter`
- path: `packages/ai-parrot/src/parrot/registry/routing/store_router.py`
  symbol: `StoreRouter`

## Notes

- The name collision matters for the spec: `registry.capabilities` is already taken by intent-routing models; a capability *directory* needs a distinct name or must extend these models deliberately.
- PBAC already gates `AgentRegistry.get_instance` (TASK-1054) — a natural anchor for the "inter-agent communication grant".
- [cross-lane: type=read, intent=read registry/capabilities/models.py and registry/registry.py get_instance to see what PBAC enforcement and 'capabilities' currently mean]
- [cross-lane: type=wiki_query, intent=EmbeddingIntentRouter / IntentRouterMixin — could be the harness-side 'find who answers' without an LLM]
