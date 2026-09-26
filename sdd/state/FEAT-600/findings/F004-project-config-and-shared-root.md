---
id: F004
query_id: Q004
type: read
intent: WikiProjectConfig: backend Literal stops at arangodb; DecisionConfig is the sub-config precedent; ledger_path/find_shared_root/is_linked_worktree exist
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — WikiProjectConfig: backend Literal stops at arangodb; DecisionConfig is the sub-config precedent; ledger_path/find_shared_root/is_linked_worktree exist

## Summary

WikiNamespaceConfig (L183) requires exactly one of path/store/database/vault; overlay_prefixes at L240. WikiProjectConfig.backend is Literal['sqlite','memory','arangodb'] (L419) — 'postgres' is not accepted even though create_wiki_store knows it. `decisions: DecisionConfig = Field(default_factory=DecisionConfig)` (L478) is the pattern for a `schema: SchemaPlaneConfig` block. ledger_path(root) L520 and storage_path(root) L532 are the path helpers; is_linked_worktree L1185 and find_shared_root L1197 implement the shared-root policy.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 183-260
  symbol: `WikiNamespaceConfig`
  excerpt: |
    Exactly one of path, store, database or vault must be set — that choice is the entry's kind
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 240
  symbol: `WikiNamespaceConfig.overlay_prefixes`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 419
  symbol: `WikiProjectConfig.backend`
  excerpt: |
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 478-485
  symbol: `WikiProjectConfig.decisions`
  excerpt: |
    decisions: DecisionConfig = Field(default_factory=DecisionConfig, …)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 520,532
  symbol: `WikiProjectConfig.ledger_path / storage_path`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 1185,1197
  symbol: `is_linked_worktree / find_shared_root`
