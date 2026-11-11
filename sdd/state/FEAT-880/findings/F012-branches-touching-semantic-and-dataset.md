---
id: F012
query_id: Q037
type: git_log
intent: "Any unmerged branch already touching semantic + dataset manager."
executed_at: 2026-11-11T22:05:20Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FG-005
---

# F012 — Nothing in flight combines semantic layer and DatasetManager; the only unmerged matches are stale (Feb) or leftover FEAT-704 sub-worktree branches

## Summary

`git log --all -i --since=120.days.ago --grep=semantic --grep=dataset --all-match` returns 4 commits; the only substantive one is `9986ac7c49` (TASK-4709, the existing hand-off, already on `dev`). The other three are an SDD id reservation for this very proposal, an SDD task-file commit, and an unrelated lint pass. `git branch -a --no-merged origin/dev` filtered to `*semantic*`/`*dataset*` leaves 4 refs: two leftover FEAT-704 per-task sub-worktree branches (2026-10-19, superseded by the merged feature) and `new-dataset-manager` (local + origin, last commit 2026-02-09, "documentdb interface"). No open branch implements a semantic source or a DuckDB-backed dataset store.

## Citations

- sha: `9ef29ae40a`  date: 2026-11-11  message: "sdd: reserve 1 feature id(s) for datasetmanager-semantic-source"  (this proposal's FEAT-880 reservation)
- sha: `9986ac7c49`  date: 2026-10-26  message: "feat(semantic-layer): TASK-4709 — guarded dataset sink and read-time authorization"  files: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
- sha: `76fd61bea7`  date: 2026-10-25  message: "sdd: add TASK-4701/TASK-4702 for semantic-layer — FEAT-742 proposal + agent e2e example"
- sha: `4adbe565e3`  date: 2026-09-23  message: "style(tool-configuration-agentstudio): FEAT-593 — full lint pass"  (unrelated; matches on words only)
- branch (unmerged into origin/dev): `new-dataset-manager` / `origin/new-dataset-manager` — tip 2026-02-09 "documentdb interface"
- branch (unmerged, local only): `feat-FEAT-704-semantic-layer--TASK-4480-a1-dde5085a3f6e4083aece77a5a6c4ac7c` — tip 2026-10-19 "style(semantic-layer): TASK-4480 — engine lint autofix"
- branch (unmerged, local only): `feat-FEAT-704-semantic-layer--TASK-4481-a1-dde5085a3f6e4083aece77a5a6c4ac7c` — tip 2026-10-19 "feat(semantic-layer): TASK-4481 — engine-committed coder deliverable"

## Notes

- Merged-but-present remote branches worth knowing as lineage, not collisions: `origin/feat-060-datasetmanager-sources`, `origin/feat-062-composite-datasets`, `origin/feat-151-pbac-datasetmanager-policy`, `origin/feat-FEAT-738-handlers-datasets-fixes`, `origin/feat-FEAT-704-semantic-layer`, `origin/feat-FEAT-769-semantic-layer-example`.
- FEAT-742 (`semantic-layer-rust-compiler`, reserved 2026-10-25 per `76fd61bea7`) is the one reserved-but-unstarted feature that would later replace the compiler a semantic source calls; a source should depend on the `engines.compile` entry point, not on `NativeCompiler` directly.
- Branch listing was limited to names matching `*semantic*` / `*dataset*`; a branch touching these areas under an unrelated name would not show.
