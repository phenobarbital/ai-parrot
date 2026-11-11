---
id: FG-004
query_id: Q063
type: git_log
intent: "Arrow transport work (FEAT-750, PR #1817, PR #1836) — commits and files, to cite the existing Arrow bridge."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 600
parent_id: null
depth: 0
---

# FG-004 — The existing Arrow bridge is the REPL-worker value codec (FEAT-750, PR #1817) hardened by PR #1836

## Summary

FEAT-750 `bots-data-fixes` had one task, TASK-4751: an Arrow value codec for `repl_worker` plus tolerant
data-variable inference in `bots/data.py`; merged with PR #1817 on 2026-10-26. A day later PR #1836
(`fix-PANDASAGENT-ARROW-repl-value-codec-allowlist`) made the codec carry pandas-3 Arrow values and widened
the unpickle allowlist, and a separate commit switched the PandasAgent REPL back to worker mode. All of this
lives in `parrot/tools/repl_worker/` — it is a process-boundary transport for REPL values, not a
DatasetManager store and not a DuckDB registration path.

## Citations

- commit: `b0106db533` — 2026-10-26 — feat(bots-data-fixes): TASK-4751 — Arrow value codec for repl_worker + tolerant data-variable inference
  files: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`,
  `packages/ai-parrot/src/parrot/bots/data.py`,
  `packages/ai-parrot/tests/repl_worker/test_protocol.py`,
  `packages/ai-parrot/tests/unit/bots/test_pandasagent_infer_tolerant.py`
- commit: `1652a97804` — 2026-10-26 — Merge pull request #1817 from phenobarbital/feat-FEAT-750-bots-data-fixes
- commit: `f514b78af6` — 2026-10-27 — fix(repl-worker): carry pandas-3 Arrow values and widen the unpickle allowlist
  files: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`,
  `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`,
  `packages/ai-parrot/tests/repl_worker/test_handle.py`,
  `packages/ai-parrot/tests/repl_worker/test_protocol.py`
- commit: `288456d508` — 2026-10-27 — Merge pull request #1836 from phenobarbital/fix-PANDASAGENT-ARROW-repl-value-codec-allowlist
- commit: `381b303e55` — 2026-10-27 — fix(agents): switch PandasAgent REPL back to worker mode after FEAT-750
  files: `agents/finance_reporter.py`, `agents/flex_dashboard.py`

## Notes

- The message filter (`FEAT-750|[Aa]rrow`) also matched unrelated commits containing "narrow"/"arrow" as a
  substring; they are omitted.
- No commit in the 45-day window adds Arrow handling to `parrot/tools/dataset_manager/` (see FG-005).
- [cross-lane: type=read, intent=read parrot/tools/repl_worker/protocol.py for the Arrow codec entry points (encode/decode names) in case the accounting DuckDB runtime can reuse the pandas→Arrow conversion]
