---
id: F012
query_id: Q012
type: git_log
intent: Identify recent memory and review changes
executed_at: 2026-09-17T21:50:09.640444+00:00
parent_id: null
depth: 0
---

# F012 — Active branch and recent history

## Summary

Research ran on dev at 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c, whereas the source says its original checks used main. Current source reads are authoritative for this proposal. Recent review changes include execution attribution; preserve it through migration.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`
  commit: 5a5474461
  date: 2026-09-16
  message: feat(sdd-coder-execution-pool-suspensions): TASK-3278 — Add execution attribution to telemetry and review history
- path: `packages/ai-parrot/src/parrot/memory`
  commit: f8c549728
  date: 2026-09-08
  message: feat(workingmemory-toolkit): TASK-2990 — wire bot turn context and single invocation persistence

## Notes

Query: git log -5 --format='%h %ad %s' --date=short -- packages/ai-parrot/src/parrot/memory packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py.
No regression causality is inferred from this history.
