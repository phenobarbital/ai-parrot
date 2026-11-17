---
id: FG-007
query_id: Q065
type: git_log
intent: "In-flight branches touching semantic / accounting / duckdb / dataset (remote and local) — collision check, incl. FEAT-742 Rust compiler and FEAT-769."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FG-007 — No in-flight branch touches the semantic package, an accounting layer or a DuckDB dataset store

## Summary

42 local and remote branches match `semantic|accounting|finance|duckdb|dataset|FEAT-742|FEAT-769|FEAT-880|FEAT-713`
(sub-worktree `--TASK-` branches excluded). 40 are fully merged into `origin/dev` (0 commits ahead), among
them `origin/feat-FEAT-704-semantic-layer`, `origin/feat-FEAT-769-semantic-layer-example`,
`origin/fix-semantic-packaging-test` and `origin/ci/release-semantic`. The only unmerged one is
`new-dataset-manager` (local + remote), 1 commit ahead, last commit 2026-02-09 — nine months stale. No
branch exists for FEAT-713, FEAT-880 or FEAT-742, and no branch name contains `duckdb` or `accounting`
(the one `accounting` hit is the merged, unrelated `feat-479-devflow-telemetry-accounting`).

## Citations

- branch: `origin/feat-FEAT-704-semantic-layer` — last commit `93e84914db` 2026-10-27 — merged into origin/dev, 0 ahead
- branch: `origin/feat-FEAT-769-semantic-layer-example` — last commit `8383b43dc9` 2026-10-30 — merged into origin/dev, 0 ahead
- branch: `origin/fix-semantic-packaging-test` — last commit `07adb66f01` 2026-10-28 — merged, 0 ahead
- branch: `origin/ci/release-semantic` — last commit `27c86d1f53` 2026-10-29 — merged, 0 ahead
- branch: `origin/fix-dataset-fetch-terminal-errors-dataset-fetch-terminal-errors` — last commit `ff4df46e8b` 2026-11-11 — merged, 0 ahead
- branch: `origin/feat-FEAT-738-handlers-datasets-fixes` — last commit `34e818d8f8` 2026-10-24 — merged, 0 ahead
- branch: `new-dataset-manager` / `origin/new-dataset-manager` — last commit `eae9ccdc4a` 2026-02-09 — NOT merged, 1 ahead (stale)
- branch: `origin/feat-479-devflow-telemetry-accounting` — last commit `067a9a2e98` 2026-08-31 — merged (dev-flow token accounting, unrelated)
- branches matching `742|rust-compiler|semaflow`: none for FEAT-742 (hits are `TASK-4742` of FEAT-746, `fixgroup-742a9ada6cba` of FEAT-827, and an issue hash)

## Notes

- Important for the old spec: `origin/feat-FEAT-704-semantic-layer` still exists but is fully merged, so
  "mirror the skeleton on that branch" (M1, AC2) and "when FEAT-704 resumes" (Q10) have no remaining object.
- FEAT-742 (Rust compiler) has no branch; whether it has a spec/proposal under `sdd/` was not checked here.
- "Merged" was tested with `git merge-base --is-ancestor <branch> origin/dev` against the `origin/dev`
  fetched at the start of this session.
- [cross-lane: type=glob, intent=is there an sdd/specs or sdd/proposals document for FEAT-742 (Rust semantic compiler) that constrains how an accounting compiler should plug into engines/]
