---
id: FG-005
query_id: Q064
type: git_log
intent: "Recent activity on GraphIndex retrieval layer."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 300
parent_id: null
depth: 0
---

# FG-005 — knowledge/retrieval/: FEAT-435 L2 retrieval built 2026-08-20 (policies, sufficiency, eval gate); only a pin-capability seam since (2026-10-15)

## Summary

10 commits in 90 days (Jesus). Eight land on 2026-08-20 as FEAT-435 GraphIndex Retrieval Layer: `SectionSelector` from `QueryClass` (TASK-2279), `DirectSymbolPolicy` no-LLM fast path (TASK-2280), `VectorSeedPolicy` FTS5 ∥ FAISS fused with RRF (TASK-2281), `SufficiencyCheck` + sequential escalation (TASK-2282), `WikiSection`/`WikiPage` per-section invalidation + single-flight (TASK-2283), golden set + eval harness + routing regression gate (TASK-2284), reserved-origin contract test "no policy may emit L2_*" (TASK-2272), adversarial review fixes. Then 2026-10-15 TASK-4322 (graphindex-core-seams) reworked `retrieval/pin.py` and the `parrot_tools.graphindex` toolkit. The L2 layer is stable since August and already has policy objects a `mode: retrieval` source can call.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/`
  lines: n/a
  symbol: `DirectSymbolPolicy`, `VectorSeedPolicy`, `SufficiencyCheck`, `SectionSelector`, `WikiSection`, `WikiPage`
  excerpt: |
    c6c5c2be33 2026-08-20 feat(FEAT-435): DirectSymbolPolicy — no-traversal, no-LLM fast path (TASK-2280)
    7f29b73c5a 2026-08-20 feat(FEAT-435): VectorSeedPolicy — FTS5 ∥ FAISS FlatL2, fused with RRF (TASK-2281)
    4f18a9a046 2026-08-20 feat(FEAT-435): SufficiencyCheck + sequential escalation driver (TASK-2282)
    d34cbfece9 2026-08-20 feat(FEAT-435): WikiSection/WikiPage + per-section invalidation + single-flight (TASK-2283)
    c28d34457c 2026-08-20 feat(FEAT-435): golden set + eval harness + routing regression gate (TASK-2284)
    385519e5ad 2026-08-20 feat(FEAT-435): reserved-origin contract test — no policy may emit L2_* (TASK-2272)

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py`
  lines: n/a
  symbol: pin capability
  excerpt: |
    15f9e5e5f7 2026-10-15 Jesus feat(graphindex-core-seams): TASK-4322
     packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py | 23 ++++-----
     packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py    |  7 +++
     packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py         | 38 ++++----------
     .../knowledge/retrieval/test_pin_capability.py                   | 59 +++++

## Notes

- The agent-facing GraphIndex surface is `parrot_tools.graphindex.toolkit` (ai-parrot-tools), not core — an expert's `toolkits:` list would name it there.
- [cross-lane: type=read, intent=retrieval/__init__.py public API + parrot_tools/graphindex/toolkit.py tool names]
