---
id: F010
query_id: Q063
type: git_log
intent: "Arrow transport work (FEAT-750, PR #1817, PR #1836) — commits and files, to cite the existing Arrow bridge."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 600
parent_id: null
depth: 0
lane_ids: [FG-004]
---

# F010 — The existing Arrow bridge is the REPL-worker value codec (FEAT-750, PR #1817) hardened by PR #1836

## Summary

FEAT-750 `bots-data-fixes` had one task, TASK-4751: an Arrow value codec for `repl_worker` plus tolerant
data-variable inference in `bots/data.py`; merged with PR #1817 on 2026-10-26. A day later PR #1836
(`fix-PANDASAGENT-ARROW-repl-value-codec-allowlist`) made the codec carry pandas-3 Arrow values and widened
the unpickle allowlist, and a separate commit switched the PandasAgent REPL back to worker mode. All of this
lives in `parrot/tools/repl_worker/` — it is a process-boundary transport for REPL values, not a
DatasetManager store and not a DuckDB registration path.

## Citations



## Notes

- The message filter (`FEAT-750|[Aa]rrow`) also matched unrelated commits containing "narrow"/"arrow" as a
  substring; they are omitted.
- No commit in the 45-day window adds Arrow handling to `parrot/tools/dataset_manager/` (see FG-005).
- [cross-lane: type=read, intent=read parrot/tools/repl_worker/protocol.py for the Arrow codec entry points (encode/decode names) in case the accounting DuckDB runtime can reuse the pandas→Arrow conversion]
