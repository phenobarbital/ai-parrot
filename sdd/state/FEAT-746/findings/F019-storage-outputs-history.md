---
id: F019
query_id: Q057
type: git_log
intent: "Recent history: storage / outputs artifacts."
executed_at: 2026-10-25T22:41:57Z
duration_ms: 350
parent_id: null
depth: 0
lane_origin: FG-007-storage-outputs-history
---

# F019 — storage/outputs history: a tenant-partitioned artifact/export store exists (Oct 2026); outputs dominated by A2UI

## Summary

15 commits in 120 days on `parrot/storage/` + `parrot/outputs/`. Relevant: "PA-11 export tools take no path arguments and write only to the artifact store" and "PA-12 tenant-partitioned export store and tenant-checked download" (revbot, 10-09) — an artifact store with tenant partitioning and authorised download already exists. The rest is A2UI work (linked recipes/transforms, KPI periods contract, lazy imports) and the telemetry hot tier (ChatStorage Redis keeps caller metadata, 10-22). No commit mentions content addressing (sha256), TTL/GC, Arrow or handles.

## Citations

- path: `packages/ai-parrot/src/parrot/storage/`
  commit: `3e5aa6a440` 2026-10-09 revbot — feat(tools): PA-11 export tools take no path arguments and write only to the artifact store
- path: `packages/ai-parrot/src/parrot/storage/`
  commit: `be60bb76b9` 2026-10-09 revbot — feat(studio): PA-12 tenant-partitioned export store and tenant-checked download
- path: `packages/ai-parrot/src/parrot/storage/`
  commit: `ab51b33d41` 2026-10-22 Jesus — feat(parrot-telemetry-event-fanout): TASK-4551 — hot tier keeps caller metadata
- path: `packages/ai-parrot/src/parrot/outputs/`
  commit: `7393cbed0c` 2026-10-14 Jesus Lara — feat(a2ui-lazy-imports): TASK-4289 — engine-committed coder deliverable
- path: `packages/ai-parrot/src/parrot/outputs/`
  commit: `5356c214c6` 2026-10-06 Jesus — feat(linked-a2ui-recipes-transforms): TASK-4107 — engine-committed coder deliverable

## Notes

[cross-lane: type=read, intent=read the PA-11/PA-12 artifact/export store module in parrot/storage to assess it as the blob-store base (keying, tenant partition, download auth)]
