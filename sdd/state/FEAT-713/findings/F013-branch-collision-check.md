---
id: F013
query_id: Q065
type: git_log
intent: "In-flight branches touching semantic / accounting / duckdb / dataset (remote and local) — collision check, incl. FEAT-742 Rust compiler and FEAT-769."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 1500
parent_id: null
depth: 0
lane_ids: [FG-007]
---

# F013 — No in-flight branch touches the semantic package, an accounting layer or a DuckDB dataset store

## Summary

42 local and remote branches match `semantic|accounting|finance|duckdb|dataset|FEAT-742|FEAT-769|FEAT-880|FEAT-713`
(sub-worktree `--TASK-` branches excluded). 40 are fully merged into `origin/dev` (0 commits ahead), among
them `origin/feat-FEAT-704-semantic-layer`, `origin/feat-FEAT-769-semantic-layer-example`,
`origin/fix-semantic-packaging-test` and `origin/ci/release-semantic`. The only unmerged one is
`new-dataset-manager` (local + remote), 1 commit ahead, last commit 2026-02-09 — nine months stale. No
branch exists for FEAT-713, FEAT-880 or FEAT-742, and no branch name contains `duckdb` or `accounting`
(the one `accounting` hit is the merged, unrelated `feat-479-devflow-telemetry-accounting`).

## Citations



## Notes

- Important for the old spec: `origin/feat-FEAT-704-semantic-layer` still exists but is fully merged, so
  "mirror the skeleton on that branch" (M1, AC2) and "when FEAT-704 resumes" (Q10) have no remaining object.
- FEAT-742 (Rust compiler) has no branch; whether it has a spec/proposal under `sdd/` was not checked here.
- "Merged" was tested with `git merge-base --is-ancestor <branch> origin/dev` against the `origin/dev`
  fetched at the start of this session.
- [cross-lane: type=glob, intent=is there an sdd/specs or sdd/proposals document for FEAT-742 (Rust semantic compiler) that constrains how an accounting compiler should plug into engines/]
