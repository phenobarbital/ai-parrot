---
id: F020
query_id: Q058
type: git_log
intent: "Recent history: semantic-layer spec and its tasks index (are result handles / audit ledger / pbac gate implemented or pending?)."
executed_at: 2026-10-25T22:41:57Z
duration_ms: 500
parent_id: null
depth: 0
lane_origin: FG-008-semantic-layer-status
---

# F020 — Semantic layer (FEAT-704): spec at rev 0.3 (2026-10-25), 26 tasks, ALL pending — handles, audit ledger and PBAC gate are planned, not shipped

## Summary

6 commits in 90 days on the spec + index: spec added 10-19, open questions resolved (rev 0.2) 10-19, 20 tasks added 10-19, spec rev 0.3 on 10-25, TASK-4701/4702 added 10-25, plus a "semantic layer" commit 10-25. Index: FEAT-704, `completed_at: null`, 26 tasks, **0 done** (all `pending`). The three overlapping tasks — TASK-4469 "Fail-closed PBAC and full column lineage (M6a)", TASK-4474 "Signed audit ledger and optional Postgres sink (M8)", TASK-4476 "Scoped result handles and exact retained provenance (M9b)" — are therefore design-only today. The brainstorm's statement that the AuditLedger is "already defined for ai-parrot" is true at spec level only (and per memory, FEAT-704's branch is salvage-only after the AGPL/sidemantic decision).

## Citations

- path: `sdd/specs/semantic-layer.spec.md`
  commit: `d7856cd3d` 2026-10-25 Jesus Lara — sdd: add spec for FEAT-704 — semantic-layer (rev 0.3)
- path: `sdd/tasks/index/semantic-layer.json`
  commit: `76fd61bea` 2026-10-25 Jesus Lara — sdd: add TASK-4701/TASK-4702 for semantic-layer — FEAT-742 proposal + agent e2e example
- path: `sdd/tasks/index/semantic-layer.json`
  commit: `05d62af07` 2026-10-19 Jesus — sdd: add 20 tasks for FEAT-704 — semantic-layer
- path: `sdd/specs/semantic-layer.spec.md`
  commit: `dd97dec23` 2026-10-19 Jesus — sdd: resolve §8 open questions for semantic-layer (FEAT-704, spec rev 0.2)
- path: `sdd/tasks/index/semantic-layer.json`
  symbol: TASK-4469 / TASK-4474 / TASK-4476
  excerpt: |
    FEAT-704 completed_at None, 26 tasks, 0 done
    TASK-4469 pending  Fail-closed PBAC and full column lineage (M6a)
    TASK-4474 pending  Signed audit ledger and optional Postgres sink (M8)
    TASK-4476 pending  Scoped result handles and exact retained provenance (M9b)
    TASK-4472 pending  Governance composition and subject/provenance digest (M6d)

## Notes

Design overlap, not code overlap: the inter-agent protocol should share the *definitions* of result handle, provenance digest and signed ledger with FEAT-704 (or own them in core so both consume them) rather than assume they exist. [cross-lane: type=read, intent=read sdd/specs/semantic-layer.spec.md sections for M8 signed audit ledger and M9b scoped result handles to lift the data model]
