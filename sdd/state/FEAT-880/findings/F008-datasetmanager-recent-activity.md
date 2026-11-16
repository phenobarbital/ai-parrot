---
id: F008
query_id: Q033
type: git_log
intent: "Recent DatasetManager activity (active refactors, collisions)."
executed_at: 2026-11-11T22:05:20Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FG-001
---

# F008 — DatasetManager is quiet: 3 commits in 45 days, all security/robustness fixes, no refactor in flight

## Summary

`git log --since=45.days.ago -- packages/ai-parrot/src/parrot/tools/dataset_manager` returns only 3 commits (2026-10-14 → 2026-11-11), all by the same author, all narrow fixes: fetch-failure classification, request-scoped RLS injection, fail-closed slug authorization. No structural refactor of `tool.py` or `sources/` is in flight on `dev`, so a new source kind has low merge-collision risk. The dominant theme is hardening the fetch/authorization path — exactly the path a semantic source would run through.

## Citations

- sha: `b396eccb4d`  date: 2026-11-11
  message: "fix(dataset-fetch-terminal-errors): classify fetch failures, stop retries on terminal ones"
  path: `packages/ai-parrot/src/parrot/tools/dataset_manager` (path-scoped log; files not expanded)
- sha: `55619c5ceb`  date: 2026-10-24
  message: "fix(dataset-manager): TASK-4678 — request-scoped RLS injection"
  files: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py`, `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`, `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/scoped_copy.py` (new)
- sha: `a44cf79608`  date: 2026-10-14
  message: "feat(fixgroup-04e6aabc0d26): TASK-4288 — fail-closed slug authorization on the QuerySlugSource fetch path"
  files: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`

## Notes

- The newest commit (`b396eccb4d`, merged via PR #2094 the day of this research) changes fetch-failure handling: a semantic source's compile/policy refusals should map onto its terminal-vs-retryable classification.
- [cross-lane: type=read, intent=read how b396eccb4d classifies terminal fetch errors in packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py so a semantic source's SemanticPolicyError/SemanticValidationError is classified terminal, not retried]
- [cross-lane: type=read, intent=read packages/ai-parrot/src/parrot/tools/dataset_manager/sources/scoped_copy.py — request-scoped RLS copy of a source (TASK-4678) is a contract any new DataSource must support]
