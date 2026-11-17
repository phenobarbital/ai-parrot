---
id: F023
query_id: Q031
type: git_log
intent: "What planogram work is on dev but not yet on main (prod pending)."
executed_at: 2026-11-06T16:04:38Z
duration_ms: 600
parent_id: null
depth: 0
lanes: [git]
merged_from: [FG-003]
---
# F023 — Planogram work on origin/dev but not on origin/main: none

## Summary

`git rev-list --count origin/main..origin/dev -- packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/` returns **0** and the matching `git log` is empty:
every planogram-cycle commit on `origin/dev` is already contained in `origin/main`. Ancestry was verified
explicitly for the three fixes the Epson endcap rows depend on — per-requirement text features
(`e168ddc9f2`, FEAT-687 line of work), the appearance rule (`dd059bfa79`, FEAT-683) and the
out-of-vocabulary appearance coercion (`b1d8d506dc`, PR #1680) — plus the two later commits; all five are
ancestors of `origin/main`. There is no unreleased planogram *code*; whatever is "pending for prod" is
configuration data and deployment, not source.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/`
  range: `origin/main..origin/dev` → 0 commits
- ancestry (`git merge-base --is-ancestor <sha> origin/main`):
  - `e168ddc9f2` 2026-10-15 feat(comparison-rules-fixes-2): TASK-4368 — per-requirement text features → IN origin/main
  - `dd059bfa79` 2026-10-15 feat(planogram-appearance-rule): TASK-4362 → IN origin/main
  - `b1d8d506dc` 2026-10-15 fix(planogram): coerce out-of-vocabulary appearance answers to unknown → IN origin/main
  - `dda9a3ed2a` 2026-10-27 fix(ci): repair nightly setup and package regressions → IN origin/main
  - `321c9883a3` 2026-11-05 feat(github-wiki-technical-reference): TASK-5172 → IN origin/main

## Notes

- Release tags are in F028 (child finding).
- "In origin/main" says nothing about which `ai-parrot-pipelines` version the Epson360 / FlowTask worker
  actually has installed — that is a deployment fact outside this repository.
